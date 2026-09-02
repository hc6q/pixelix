#!/usr/bin/env python3
from pathlib import Path
import re

root = Path(".")
health_path = root / "AuraHealth/Services/HealthKitService.swift"
app_path = root / "AuraHealth/App/AuraHealthApp.swift"

health = health_path.read_text(encoding="utf-8")
app = app_path.read_text(encoding="utf-8")

old_lookup = '''    /// Pre-fetched lookup of existing measurements to avoid N+1 queries during import
    private var existingMeasurements: Set<String> = []

    private func buildExistingLookup(context: ModelContext, since startDate: Date) {
        let descriptor = FetchDescriptor<Measurement>(
            predicate: #Predicate { $0.timestamp >= startDate }
        )
        let all = (try? context.fetch(descriptor)) ?? []
        existingMeasurements = Set(all.map { measurement in
            let day = Calendar.current.startOfDay(for: measurement.timestamp)
            return "\\(measurement.metricType.rawValue)-\\(measurement.source.rawValue)-\\(day.timeIntervalSince1970)"
        })
    }
'''

new_lookup = '''    /// Pre-fetched lookup of existing measurements so daily HealthKit values can be updated in place.
    private var existingMeasurements: [String: Measurement] = [:]

    private func measurementKey(timestamp: Date, type: MetricType, source: MeasurementSource = .appleHealth) -> String {
        let day = Calendar.current.startOfDay(for: timestamp)
        return "\\(type.rawValue)-\\(source.rawValue)-\\(day.timeIntervalSince1970)"
    }

    private func buildExistingLookup(context: ModelContext, since startDate: Date) {
        let descriptor = FetchDescriptor<Measurement>(
            predicate: #Predicate { $0.timestamp >= startDate }
        )
        let all = (try? context.fetch(descriptor)) ?? []
        existingMeasurements.removeAll(keepingCapacity: true)
        for measurement in all {
            let key = measurementKey(
                timestamp: measurement.timestamp,
                type: measurement.metricType,
                source: measurement.source
            )
            existingMeasurements[key] = measurement
        }
    }
'''

if old_lookup in health:
    health = health.replace(old_lookup, new_lookup)
elif "private var existingMeasurements: [String: Measurement]" not in health:
    raise SystemExit("Aura patch: existing measurement lookup changed upstream; review required")

old_start = '''        let startDate = Calendar.current.date(byAdding: .day, value: -days, to: Date())!

        // Build lookup once instead of querying per-item
        buildExistingLookup(context: context, since: startDate)
'''
new_start = '''        let startDate = Calendar.current.date(byAdding: .day, value: -days, to: Date())!
        // Weight sync reaches back a full year, so preload that entire window as well.
        let lookupStartDate = Calendar.current.date(byAdding: .day, value: -365, to: Date())!

        // Build one lookup so existing daily values can be updated instead of skipped.
        buildExistingLookup(context: context, since: lookupStartDate)
'''
if old_start in health:
    health = health.replace(old_start, new_start)
elif "lookupStartDate" not in health:
    raise SystemExit("Aura patch: sync lookup window changed upstream; review required")

# Daily metrics should update the existing Apple Health measurement for the day.
health = health.replace("if insertIfNew(context: context, timestamp: day, type: metricType, value: value) {", "if upsertDaily(context: context, timestamp: day, type: metricType, value: value) {")
health = health.replace("if insertIfNew(context: context, timestamp: day, type: metricType, value: total) {", "if upsertDaily(context: context, timestamp: day, type: metricType, value: total) {")
health = health.replace("if insertIfNew(context: context, timestamp: night, type: .sleepDuration, value: totalSleep) {", "if upsertDaily(context: context, timestamp: night, type: .sleepDuration, value: totalSleep) {")

# Weight already had update behavior; adapt its insertion path to the dictionary lookup.
old_weight_insert = '''                if !existingMeasurements.contains(key) {
                    existingMeasurements.insert(key)
                    context.insert(Measurement(timestamp: day, metricType: .weight, value: value, source: .appleHealth))
                    syncProgress?.imported += 1
                    inserted += 1
                }
'''
new_weight_insert = '''                if existingMeasurements[key] == nil {
                    let measurement = Measurement(timestamp: day, metricType: .weight, value: value, source: .appleHealth)
                    context.insert(measurement)
                    existingMeasurements[key] = measurement
                    syncProgress?.imported += 1
                    inserted += 1
                }
'''
if old_weight_insert in health:
    health = health.replace(old_weight_insert, new_weight_insert)
elif "existingMeasurements[key] == nil" not in health:
    raise SystemExit("Aura patch: weight insertion changed upstream; review required")

# Blood pressure used to keep the first value forever. Keep the latest sample per day and update it.
new_bp = '''    private func syncBloodPressure(context: ModelContext, since startDate: Date) async throws {
        guard let systolicType = HKQuantityType.quantityType(forIdentifier: .bloodPressureSystolic),
              let diastolicType = HKQuantityType.quantityType(forIdentifier: .bloodPressureDiastolic) else { return }

        let predicate = HKQuery.predicateForSamples(withStart: startDate, end: Date())
        let mmHg = HKUnit.millimeterOfMercury()

        let sysDescriptor = HKSampleQueryDescriptor(
            predicates: [.quantitySample(type: systolicType, predicate: predicate)],
            sortDescriptors: [SortDescriptor(\\.startDate, order: .reverse)],
            limit: 500
        )

        let diasDescriptor = HKSampleQueryDescriptor(
            predicates: [.quantitySample(type: diastolicType, predicate: predicate)],
            sortDescriptors: [SortDescriptor(\\.startDate, order: .reverse)],
            limit: 500
        )

        let systolicSamples = try await sysDescriptor.result(for: healthStore)
        let diastolicSamples = try await diasDescriptor.result(for: healthStore)
        let cal = Calendar.current
        let systolicByDay = Dictionary(grouping: systolicSamples) { cal.startOfDay(for: $0.startDate) }
        let diastolicByDate = Dictionary(grouping: diastolicSamples) { $0.startDate }

        var changed = 0
        for (_, daySamples) in systolicByDay {
            guard let sys = daySamples.first else { continue }
            let sysValue = sys.quantity.doubleValue(for: mmHg)
            let diaValue = diastolicByDate[sys.startDate]?.first?.quantity.doubleValue(for: mmHg)

            if upsertDaily(
                context: context,
                timestamp: sys.startDate,
                type: .bloodPressure,
                value: sysValue,
                value2: diaValue
            ) {
                syncProgress?.imported += 1
                changed += 1
            }
        }
        logger.notice("[HealthKit] Blood Pressure: \\(systolicSamples.count) samples → \\(systolicByDay.count) days → \\(changed) new/updated")
    }

'''
health, bp_count = re.subn(
    r"    private func syncBloodPressure\(context: ModelContext, since startDate: Date\) async throws \{.*?\n    \}\n\n(?=    private func syncSleep)",
    new_bp,
    health,
    count=1,
    flags=re.S,
)
if bp_count != 1 and "Blood Pressure:" not in health:
    raise SystemExit("Aura patch: blood pressure function changed upstream; review required")

old_helper_pattern = r'''    @discardableResult\n    private func insertIfNew\(context: ModelContext, timestamp: Date, type: MetricType, value: Double\) -> Bool \{.*?\n    \}\n'''
new_helper = '''    /// Insert a daily HealthKit value or update the existing value when Health changes during the day.
    @discardableResult
    private func upsertDaily(
        context: ModelContext,
        timestamp: Date,
        type: MetricType,
        value: Double,
        value2: Double? = nil
    ) -> Bool {
        let key = measurementKey(timestamp: timestamp, type: type)

        if let existing = existingMeasurements[key] {
            let secondaryChanged: Bool
            switch (existing.value2, value2) {
            case (nil, nil):
                secondaryChanged = false
            case let (lhs?, rhs?):
                secondaryChanged = abs(lhs - rhs) > 0.0001
            default:
                secondaryChanged = true
            }

            let changed = abs(existing.value - value) > 0.0001 || secondaryChanged
            if changed {
                existing.timestamp = timestamp
                existing.value = value
                existing.value2 = value2
            }
            return changed
        }

        let measurement = Measurement(
            timestamp: timestamp,
            metricType: type,
            value: value,
            value2: value2,
            source: .appleHealth
        )
        context.insert(measurement)
        existingMeasurements[key] = measurement
        return true
    }
'''
health, helper_count = re.subn(old_helper_pattern, new_helper, health, count=1, flags=re.S)
if helper_count != 1 and "private func upsertDaily(" not in health:
    raise SystemExit("Aura patch: insert helper changed upstream; review required")

if "insertIfNew(" in health:
    raise SystemExit("Aura patch: an old insertIfNew call remains")

# Auto-sync once on launch and every time the app returns to the foreground, but only after the user has authorized HealthKit.
if "@Environment(\\.scenePhase) private var scenePhase" not in app:
    app = app.replace(
        "struct AuraHealthApp: App {\n",
        "struct AuraHealthApp: App {\n    @Environment(\\.scenePhase) private var scenePhase\n",
        1,
    )

old_env_tail = '''            #if os(macOS)
            .environment(healthAutoExportService)
            #endif
'''
new_env_tail = '''            #if os(macOS)
            .environment(healthAutoExportService)
            #endif
            #if os(iOS)
            .task {
                await syncHealthIfNeeded()
            }
            .onChange(of: scenePhase) { _, newPhase in
                guard newPhase == .active else { return }
                Task { await syncHealthIfNeeded() }
            }
            #endif
'''
if old_env_tail in app and "await syncHealthIfNeeded()" not in app:
    app = app.replace(old_env_tail, new_env_tail, 1)

method_marker = "\n    var body: some Scene {\n"
auto_method = '''
    #if os(iOS)
    @MainActor
    private func syncHealthIfNeeded() async {
        guard hasCompletedOnboarding,
              healthKitService.isAuthorized,
              !healthKitService.isSyncing else { return }
        await healthKitService.syncData(into: auraContainer.mainContext)
    }
    #endif
'''
if "private func syncHealthIfNeeded()" not in app:
    if method_marker not in app:
        raise SystemExit("Aura patch: app body marker changed upstream; review required")
    app = app.replace(method_marker, auto_method + method_marker, 1)

health_path.write_text(health, encoding="utf-8")
app_path.write_text(app, encoding="utf-8")
print("Applied Aura Health patches: daily HealthKit upserts + foreground auto-sync")
