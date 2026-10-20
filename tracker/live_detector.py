import mediapipe as mp
import cv2

BaseOptions = mp.tasks.BaseOptions
ObjectDetector = mp.tasks.vision.ObjectDetector
ObjectDetectorOptions = mp.tasks.vision.ObjectDetectorOptions
VisionRunningMode = mp.tasks.vision.RunningMode

model_path = './efficientdet_lite0.tflite'

options = ObjectDetectorOptions(
    base_options=BaseOptions(model_asset_path=model_path),
    running_mode=VisionRunningMode.IMAGE,
    max_results=5,
    score_threshold=0.4
)

with ObjectDetector.create_from_options(options) as detector:
    # Open the default webcam (usually index 0)
    cap = cv2.VideoCapture(0)

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            print("Failed to read from webcam.")
            break

        # Convert frame to MediaPipe format
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        # Run detection on the current frame
        detection_result = detector.detect(mp_image)

        # Draw the results
        for detection in detection_result.detections:
            bbox = detection.bounding_box
            start_point = (bbox.origin_x, bbox.origin_y)
            end_point = (bbox.origin_x + bbox.width, bbox.origin_y + bbox.height)
            
            cv2.rectangle(frame, start_point, end_point, (0, 255, 0), 3)
            
            category = detection.categories[0]
            label = f"{category.category_name} ({round(category.score, 2)})"
            
            cv2.putText(frame, label, (bbox.origin_x, bbox.origin_y - 10), 
                        cv2.FONT_HERSHEY_PLAIN, 2, (0, 0, 255), 2)

        # Show the live stream
        cv2.imshow('Live Object Detection', frame)

        # Press 'q' on your keyboard to quit the live stream
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Clean up
    cap.release()
    cv2.destroyAllWindows()