#!/usr/bin/env python3
from pathlib import Path

health_path = Path("AuraHealth/Services/HealthKitService.swift")
today_path = Path("AuraHealth/Views/Today/TodayView.swift")
settings_path = Path("AuraHealth/Views/Settings/SettingsView.swift")

health = health_path.read_text(encoding="utf-8")
today = today_path.read_text(encoding="utf-8")
settings = settings_path.read_text(encoding="utf-8")

# Always choose the actually newest sample in each day instead of relying on
# Dictionary(grouping:) retaining the query's sort order.
health = health.replace(
    "guard let latest = daySamples.first else { continue }",
    "guard let latest = daySamples.max(by: { $0.startDate < $1.startDate }) else { continue }",
)
health = health.replace(
    "guard let sys = daySamples.first else { continue }",
    "guard let sys = daySamples.max(by: { $0.startDate < $1.startDate }) else { continue }",
)

# Instantaneous measurements (heart rate, HRV, SpO2, temperature) need the
# real HealthKit sample timestamp. v1 stored start-of-day, which made a fresh
# value appear many hours old in the Vitals card.
health = health.replace(
    "upsertDaily(context: context, timestamp: day, type: metricType, value: value)",
    "upsertDaily(context: context, timestamp: latest.startDate, type: metricType, value: value)",
)

# Cumulative values remain one record per day, but use the end time of the
# newest HealthKit sample as their freshness timestamp.
health = health.replace(
    "upsertDaily(context: context, timestamp: day, type: metricType, value: total)",
    "upsertDaily(context: context, timestamp: daySamples.map(\\.endDate).max() ?? day, type: metricType, value: total)",
)
health = health.replace(
    "upsertDaily(context: context, timestamp: night, type: .sleepDuration, value: totalSleep)",
    "upsertDaily(context: context, timestamp: nightSamples.map(\\.endDate).max() ?? night, type: .sleepDuration, value: totalSleep)",
)

# Weight should also keep the real timestamp of the latest sample.
health = health.replace(
    "let measurement = Measurement(timestamp: day, metricType: .weight, value: value, source: .appleHealth)",
    "let measurement = Measurement(timestamp: latest.startDate, metricType: .weight, value: value, source: .appleHealth)",
)
old_weight_existing = '''            if let existing = existingByDay[day]?.first {
                // Update if value changed (more than 0.05 kg difference)
                if abs(existing.value - value) > 0.05 {
                    existing.value = value
                    updated += 1
                }
'''
new_weight_existing = '''            if let existing = existingByDay[day]?.first {
                let timestampChanged = latest.startDate > existing.timestamp
                let valueChanged = abs(existing.value - value) > 0.05
                if timestampChanged {
                    existing.timestamp = latest.startDate
                }
                if valueChanged {
                    existing.value = value
                }
                if timestampChanged || valueChanged {
                    updated += 1
                }
'''
if old_weight_existing in health:
    health = health.replace(old_weight_existing, new_weight_existing, 1)

# If an older build ever created duplicate same-day records, prefer the newest
# one deterministically when building the lookup.
health = health.replace(
    "for measurement in all {\n            let key = measurementKey(",
    "for measurement in all.sorted(by: { $0.timestamp < $1.timestamp }) {\n            let key = measurementKey(",
    1,
)

# A new HealthKit sample can have the same numeric value as the previous one.
# Its timestamp still needs to advance so the UI reflects that the data is fresh.
old_changed = '''            let changed = abs(existing.value - value) > 0.0001 || secondaryChanged
            if changed {
                existing.timestamp = timestamp
                existing.value = value
                existing.value2 = value2
            }
            return changed
'''
new_changed = '''            let valueChanged = abs(existing.value - value) > 0.0001
            let timestampChanged = timestamp > existing.timestamp
            let changed = valueChanged || secondaryChanged || timestampChanged
            if changed {
                if timestampChanged {
                    existing.timestamp = timestamp
                }
                existing.value = value
                existing.value2 = value2
            }
            return changed
'''
if old_changed not in health:
    raise SystemExit("Aura v2 patch: upsert helper changed unexpectedly")
health = health.replace(old_changed, new_changed, 1)

# Vitals itself also requests a sync when it appears. This complements the
# app-level launch/foreground sync and catches cases where Health data arrives
# just after app activation.
model_context_line = '    @Environment(\\.modelContext) private var modelContext\n'
if '@Environment(HealthKitService.self) private var healthKitService' not in today:
    if model_context_line not in today:
        raise SystemExit("Aura v2 patch: Vitals modelContext marker not found")
    today = today.replace(
        model_context_line,
        model_context_line + '    @Environment(HealthKitService.self) private var healthKitService\n',
        1,
    )

nav_marker = '        .navigationTitle("Vitals")\n'
if '.task {\n            await syncHealthIfNeeded()\n        }' not in today:
    if nav_marker not in today:
        raise SystemExit("Aura v2 patch: Vitals navigation marker not found")
    today = today.replace(
        nav_marker,
        '        .task {\n            await syncHealthIfNeeded()\n        }\n' + nav_marker,
        1,
    )

helper_marker = '    // MARK: - Today Content (card grid)\n'
helper = '''    @MainActor
    private func syncHealthIfNeeded() async {
        guard healthKitService.isAvailable,
              healthKitService.isAuthorized,
              !healthKitService.isSyncing else { return }
        await healthKitService.syncData(into: modelContext)
    }

'''
if 'private func syncHealthIfNeeded() async' not in today:
    if helper_marker not in today:
        raise SystemExit("Aura v2 patch: Vitals helper marker not found")
    today = today.replace(helper_marker, helper + helper_marker, 1)

# Show the actual build version in Settings instead of the upstream hard-coded 1.0.0.
settings = settings.replace(
    'Text("1.0.0").foregroundStyle(.secondary)',
    'Text(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—").foregroundStyle(.secondary)',
    1,
)

health_path.write_text(health, encoding="utf-8")
today_path.write_text(today, encoding="utf-8")
settings_path.write_text(settings, encoding="utf-8")
print("Applied Aura Health v2 patch: real sample timestamps + Vitals appearance sync")
