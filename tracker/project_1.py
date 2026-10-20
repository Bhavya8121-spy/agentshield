import cv2
import mediapipe as mp
import numpy as np

# --- 1. SETUP ---
mp_drawing = mp.solutions.drawing_utils
mp_hands = mp.solutions.hands

# --- 2. THE DYNAMIC MEMORY BUFFER ---
current_stroke = []
predicted_text = ""

# --- 3. THE "BRAIN" (Continuous Prediction) ---
def predict_letter(stroke_coordinates):
    """
    This is where your ML model or geometric algorithm goes!
    It constantly analyzes the growing list of (x,y) coordinates.
    It returns a letter ONLY if it reaches 95%+ confidence.
    Otherwise, it returns None, meaning "Keep drawing..."
    """
    # FAKE LOGIC FOR TESTING: If the line gets longer than 40 frames, 
    # assume it's an 'A' and trigger the flush.
    if len(stroke_coordinates) > 40: 
        return "A" 
    
    return None

# --- 4. THE INGESTION LOOP ---
cap = cv2.VideoCapture(0)

with mp_hands.Hands(
    model_complexity=0,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5) as hands:
    
    while cap.isOpened():
        success, image = cap.read()
        if not success:
            continue

        # Mirror the image so drawing feels natural
        image = cv2.flip(image, 1) 
        image_height, image_width, _ = image.shape
        
        # Convert BGR to RGB for MediaPipe
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb_image)

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                
                # Extract Index finger points
                index_tip = hand_landmarks.landmark[8]
                index_knuckle = hand_landmarks.landmark[5]
                
                # Extract Middle finger points
                middle_tip = hand_landmarks.landmark[12]
                middle_knuckle = hand_landmarks.landmark[9]

                # Convert to screen pixels
                cx = int(index_tip.x * image_width)
                cy = int(index_tip.y * image_height)
                
                # --- 5. THE STATE MACHINE ---
                # DRAW MODE: Index tip is UP (higher than its knuckle) 
                # AND Middle tip is DOWN (lower than its knuckle)
                is_drawing = (index_tip.y < index_knuckle.y) and (middle_tip.y > middle_knuckle.y)
                
                if is_drawing:
                    # A. Add current position to the memory buffer
                    current_stroke.append((cx, cy))
                    
                    # B. Draw the visual trail on the screen
                    for i in range(1, len(current_stroke)):
                        cv2.line(image, current_stroke[i-1], current_stroke[i], (0, 255, 0), 4)
                        
                    # C. Feed the buffer to the brain continuously!
                    prediction = predict_letter(current_stroke)
                    
                    # D. THE TRIGGER & FLUSH
                    if prediction is not None:
                        predicted_text += prediction  # Add letter to screen
                        current_stroke.clear()        # Flush memory instantly!
                else:
                    # PAUSE MODE: Show a red dot so the user knows they are not drawing
                    cv2.circle(image, (cx, cy), 10, (0, 0, 255), cv2.FILLED)
                    
                    # Optional: If they stop drawing, clear the stroke to start fresh next time
                    current_stroke.clear() 

        # --- 6. RENDERING ---
        # Display the final predicted text on the screen
        cv2.putText(image, f"Output: {predicted_text}", (50, 70), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)

        cv2.imshow('Air Canvas AI', image)

        # Press ESC to quit
        if cv2.waitKey(5) & 0xFF == 27: 
            break

# Clean up hardware resources
cap.release()
cv2.destroyAllWindows()