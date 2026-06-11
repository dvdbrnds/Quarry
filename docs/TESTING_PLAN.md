# Bird Dog — MVP Field Testing Plan

**Version:** 1.0
**Date:** March 30, 2026

---

## 1. Purpose

Validate that Bird Dog can reliably read license plates at close range in real parking lot conditions. This test determines whether the core technology works well enough to proceed with database integration and the full product.

## 2. Test Approach

Walk (or drive a golf cart at low speed) past parked vehicles. Let the app scan continuously. Manually record every plate you pass. Compare the manual list to the app's exported log.

## 3. Test Conditions

### 3.1 Controlled Test (Do This First)

Before going to a parking lot, test with a single vehicle in a controlled setting:

- Hold the iPhone at 2, 4, and 6 feet from a plate
- Test head-on, 15° angle, 30° angle, 45° angle
- Test front plates and rear plates
- Test in direct sunlight, shade, and overcast
- Test PA plates and any out-of-state plates available
- Record: plate text, distance, angle, lighting, result (correct / incorrect / missed)

This gives you a quick read on the practical limits of the recognition.

### 3.2 Parking Lot Field Test

Pick a small lot (20-40 cars). Walk the lot at a normal walking pace (~3 mph) holding the phone at roughly the distance/angle a golf cart mount would give.

**What to record manually:**
- Total number of vehicles in the lot
- Every plate you pass (write them down or have a second person record)
- Any plates that are obstructed, dirty, or unusual (vanity plates, paper temps, etc.)

**What the app records automatically:**
- Every plate it detects with timestamp and confidence

### 3.3 Test Matrix

| Condition | Details |
|-----------|---------|
| Time of day | Morning (9-10am), midday (12-1pm), late afternoon (4-5pm) |
| Weather | Sunny, overcast, light rain (if practical) |
| Distance | 2-6 feet (expected golf cart range) |
| Speed | Walking pace (~3 mph), slow golf cart (~5 mph) |
| Device | iPhone (initial), iPad (when available) |

You don't need to test every combination. Start with the best-case scenario (midday, sunny, walking pace, 3 feet) and then test edge cases.

## 4. Metrics

### 4.1 Primary Metrics

**Detection Rate** = plates detected by app / total plates you walked past

Target: ≥ 95%

**Accuracy Rate** = plates correctly read / plates detected

Target: ≥ 95%

**False Positive Rate** = non-plate text flagged as plates / total detections

Target: < 5%

### 4.2 How to Calculate

After each test run:

1. Export the app's CSV log
2. Compare against your manual list
3. Categorize each plate as: correct, incorrect (detected but wrong text), or missed (not detected at all)
4. Note any false positives (app flagged something that wasn't a plate)

### 4.3 Spreadsheet Template

Create a simple spreadsheet:

| Manual Plate | App Read | Match? | Distance | Angle | Lighting | Notes |
|-------------|----------|--------|----------|-------|----------|-------|
| ABC-1234 | ABC1234 | Yes (normalized) | 4ft | Head-on | Sun | |
| XYZ-5678 | XYZ-5678 | Yes | 3ft | 15° | Sun | |
| DEF-9012 | (missed) | No | 6ft | 45° | Shade | Dirty plate |

## 5. Known Challenges to Watch For

- **Temporary paper plates** — these may not be readable by OCR; note how many you encounter
- **Vanity plates** — unusual character combinations might not match the plate pattern filter
- **Plate frames/covers** — dealer frames or tinted covers can obscure characters
- **Lighting glare** — reflective plates in direct sunlight can wash out the camera
- **Dirty/faded plates** — older plates with worn text
- **Stacked text** — some plates have the state name or county in small text that might confuse the filter

## 6. Go/No-Go Criteria

**GO — proceed to Phase 2 (database integration):**
- Detection rate ≥ 90% in best-case conditions
- Accuracy rate ≥ 90% on detected plates
- App runs stably for 20+ minutes of continuous scanning
- Works on the target iPad hardware

**ITERATE — tweak recognition and retest:**
- Detection rate 70-89%
- Accuracy rate 70-89%
- Likely fixes: adjust confidence threshold, frame processing rate, or pattern matching

**NO-GO — reconsider approach:**
- Detection rate < 70%
- Frequent crashes or memory issues
- iPad hardware can't keep up with processing

If results are borderline, look at the failure patterns. If most misses are edge cases (paper temps, extreme angles), that's fine — those are real-world limitations any LPR system has. If the app is missing clean, well-lit plates at close range, there's a problem.

## 7. Test Checklist

- [ ] App installed on iPhone, building and running
- [ ] Controlled single-vehicle test completed
- [ ] Results logged — detection and accuracy acceptable
- [ ] Small parking lot field test completed (20-40 cars)
- [ ] CSV exported and compared against manual count
- [ ] Metrics calculated: detection rate, accuracy rate, false positive rate
- [ ] Edge cases documented (what the app struggles with)
- [ ] Decision made: GO / ITERATE / NO-GO
- [ ] If GO: repeat test on target iPad
- [ ] iPad test results logged and compared to iPhone results
