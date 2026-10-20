import mediapipe as mp
import cv2

BaseOptions = mp.tasks.BaseOptions
ObjectDetector = mp.tasks.vision.ObjectDetector
ObjectDetectorOptions = mp.tasks.vision.ObjectDetectorOptions
VisionRunningMode = mp.tasks.vision.RunningMode

model_path = './efficientdet_lite0.tflite'
image_path = './test.jpeg'

options = ObjectDetectorOptions(
    base_options=BaseOptions(model_asset_path=model_path),
    running_mode=VisionRunningMode.IMAGE,
    max_results=5
)

with ObjectDetector.create_from_options(options) as detector:
    # 1. Load the image using OpenCV so we can draw on it
    cv_image = cv2.imread(image_path)
    
    # 2. Convert to MediaPipe format (OpenCV uses BGR, MediaPipe needs RGB)
    rgb_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
    
    # 3. Run detection
    detection_result = detector.detect(mp_image)
    
    # 4. Loop through every detected object and draw it
    for detection in detection_result.detections:
        # Get coordinates
        bbox = detection.bounding_box
        start_point = (bbox.origin_x, bbox.origin_y)
        end_point = (bbox.origin_x + bbox.width, bbox.origin_y + bbox.height)
        
        # Draw a green rectangle (BGR color: 0, 255, 0)
        cv2.rectangle(cv_image, start_point, end_point, (0, 255, 0), 3)
        
        # Get the category name and score
        category = detection.categories[0]
        category_name = category.category_name
        probability = round(category.score, 2)
        result_text = f"{category_name} ({probability})"
        
        # Draw the text label just above the box
        text_location = (bbox.origin_x, bbox.origin_y - 10)
        cv2.putText(cv_image, result_text, text_location, cv2.FONT_HERSHEY_PLAIN, 1.5, (0, 0, 255), 2)

    # 5. Show the image in a popup window
    cv2.imshow('Object Detection', cv_image)
    cv2.waitKey(0) # Wait for you to press any key to close the window
    cv2.destroyAllWindows()