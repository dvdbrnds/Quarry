# Bird Dog — Cursor Development Prompts

**How to use this document:** Work through these prompts in order. Each one builds on the previous step. Copy the prompt into Cursor's AI chat, let it generate the code, review, and iterate before moving to the next. Each prompt includes context about what should already exist so Cursor can orient itself.

---

## Prompt 1: Project Setup

```
Create a new SwiftUI iOS app called "Bird Dog". Set the deployment target to iOS 17.0.
It should be a universal app (iPhone and iPad).

Set up the project structure with these groups/folders:
- Models/
- Services/
- ViewModels/
- Views/
- Utilities/

In Info.plist, add NSCameraUsageDescription with the text:
"Bird Dog needs camera access to scan license plates."

Create a basic ContentView that just shows the text "Bird Dog" centered on screen.
Make sure the app builds and runs.
```

---

## Prompt 2: Camera Preview

```
In the Bird Dog app, create a camera preview that shows the live back camera feed.

Create these files:

1. Services/CameraService.swift
   - A class that manages an AVCaptureSession
   - Configure it to use the back wide-angle camera
   - Set the session preset to .high
   - Add an AVCaptureVideoDataOutput that delivers frames via delegate
   - Use a dedicated DispatchQueue named "com.birddog.camera" for frame delivery
   - Include start() and stop() methods for the session
   - Run start/stop on a background queue (not main thread)

2. Views/CameraPreviewView.swift
   - A UIViewRepresentable that wraps AVCaptureVideoPreviewLayer
   - Takes the AVCaptureSession as input
   - The preview layer should use .resizeAspectFill as its video gravity
   - Handle layout updates so the preview layer resizes with the view

3. Update ContentView.swift
   - Show the CameraPreviewView full-screen
   - Initialize CameraService and start the session on appear
   - Stop the session on disappear
   - Handle the case where camera permission hasn't been granted yet —
     show a message with instructions to enable it in Settings

The camera feed should fill the screen. No other UI elements yet.
Test that it builds and shows the live camera feed on a real device.
```

---

## Prompt 3: Text Recognition Pipeline

```
In the Bird Dog app, add license plate text recognition to the camera feed.

The CameraService is already set up with AVCaptureVideoDataOutput delivering
CMSampleBuffer frames on a background queue.

Create these files:

1. Services/PlateRecognitionService.swift
   - A class that processes camera frames for license plate text
   - Method: recognizePlates(in sampleBuffer: CMSampleBuffer,
     orientation: CGImagePropertyOrientation,
     completion: @escaping ([RecognizedPlate]) -> Void)
   - Use VNRecognizeTextRequest with:
     - recognitionLevel = .accurate
     - usesLanguageCorrection = false (plates aren't words)
   - Create VNImageRequestHandler from the sample buffer's pixel buffer
   - For each VNRecognizedTextObservation, get the top candidate
   - Only keep results with confidence >= 0.8
   - Return results as [RecognizedPlate] (create this struct if needed)

2. Models/ScannedPlate.swift
   - struct RecognizedPlate: plate text (String), confidence (Float),
     bounding box (CGRect), timestamp (Date)
   - struct ScannedPlate: Identifiable — plate text (String),
     timestamp (Date), confidence (Float)
     This is what goes in the log.

3. Utilities/PlatePatternMatcher.swift
   - A static function: looksLikePlate(_ text: String) -> Bool
   - Clean the text: uppercase, remove spaces
   - Match against a broad pattern: 2-8 alphanumeric characters
   - Must contain at least one letter AND at least one number
   - This is intentionally broad — we want to catch all plates,
     not just PA format

Now wire it up:

4. Update CameraService to:
   - Only process every 5th frame (use a frame counter)
   - Pass frames to PlateRecognitionService
   - Use a flag to skip frames if a recognition request is still in-flight
   - Get the current device orientation and convert to
     CGImagePropertyOrientation for the Vision request

5. Create ViewModels/PlateReaderViewModel.swift
   - ObservableObject
   - @Published var currentPlates: [RecognizedPlate] (what's visible now)
   - @Published var scanLog: [ScannedPlate] (cumulative log)
   - Method to receive recognized plates from the service
   - Deduplication: if the same plate text was logged within the last
     5 seconds, don't log it again
   - All UI updates on main thread

Don't update the UI yet — just make sure the pipeline compiles and the
ViewModel is receiving plate data. Add a print statement so you can see
recognized plates in the Xcode console.
```

---

## Prompt 4: On-Screen Plate Display

```
In the Bird Dog app, the plate recognition pipeline is working and printing
recognized plates to the console. Now add the UI.

Update the ContentView to use PlateReaderViewModel and show:

1. Camera feed taking up approximately the top 65% of the screen

2. Plate overlay on the camera feed (Views/PlateOverlayView.swift):
   - Show the most recently detected plate number in large, bold text
   - Use a semi-transparent dark background behind the text for readability
   - Position it near the bottom of the camera preview area
   - If no plate is currently detected, show nothing
   - The text should appear/disappear with a subtle animation

3. Scan log in the bottom 35% (Views/ScanLogView.swift):
   - A scrollable list showing all logged plates
   - Each row: timestamp (HH:mm:ss format) and plate text
   - Most recent plates at the top
   - Show a count of total unique plates scanned at the top of the log

4. Layout should work on both iPhone (portrait) and iPad (landscape).
   Use GeometryReader or adaptive layout so the split adjusts reasonably
   for different screen sizes.

Keep it clean and functional — no fancy styling needed. Dark background,
white text, monospaced font for plate numbers.
```

---

## Prompt 5: Export Functionality

```
In the Bird Dog app, add the ability to export the scan log.

1. Create Utilities/LogExporter.swift:
   - Function to export scanLog as CSV with columns:
     timestamp (ISO 8601), plate_text, confidence
   - Function to export as JSON array of objects with the same fields
   - Both return a URL to a temporary file

2. Add an Export button to the ContentView:
   - Place it below the scan log
   - When tapped, present a share sheet (UIActivityViewController
     via UIViewControllerRepresentable) with the CSV file
   - Include the session date in the filename: birddog_scan_YYYY-MM-DD_HHmmss.csv

3. Also add a Clear button next to Export that resets the scan log
   (with a confirmation alert).

4. Add a session timer or start time display somewhere subtle so
   the officer knows when scanning started.
```

---

## Prompt 6: Polish and Stability

```
In the Bird Dog app, do a polish pass for stability and usability:

1. Memory management:
   - Ensure CMSampleBuffer references are not retained longer than needed
   - The recognition service should not queue up work — skip frames
     if busy
   - Test for memory leaks with Instruments if possible

2. Error handling:
   - Camera permission denied: clear message with button to open Settings
   - Camera not available: appropriate message
   - Recognition failures: silent (don't crash, just skip the frame)

3. App lifecycle:
   - Stop camera session when app goes to background
   - Restart when returning to foreground
   - Preserve scan log across background/foreground transitions
     (it's in memory, just don't reset it)

4. iPad considerations:
   - Support all orientations
   - Camera orientation must match device orientation for correct
     Vision processing
   - Layout should look good in both portrait and landscape on iPad

5. Add a simple app icon placeholder and launch screen.

6. Ensure the app runs smoothly on older hardware — if recognition
   is slow, drop to processing every 10th frame instead of every 5th.
   Consider making this adaptive based on processing time.
```

---

## Tips for Working with Cursor

- **One prompt at a time.** Don't skip ahead. Each builds on the last.
- **Build and run after each prompt.** Fix any issues before moving on.
- **Test on a real device.** The camera doesn't work in the simulator. You can test UI layout in the simulator but plate recognition must be tested on hardware.
- **If Cursor generates something that doesn't compile,** paste the error back into Cursor with context: "I got this build error: [error]. The project structure is [describe]. Fix it."
- **Keep the project structure clean.** If Cursor puts a file in the wrong place, move it before continuing.
- **Reference the Architecture doc.** If Cursor goes off-track, paste the relevant section of ARCHITECTURE.md and say "follow this architecture."
