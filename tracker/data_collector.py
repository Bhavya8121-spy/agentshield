import cv2
import mediapipe as mp
import csv
import os

# --- 1. SETUP ---
mp_hands = mp.solutions.hands
current_stroke = []

# --- 2. DEBOUNCE / DELAY LOGIC ---
DRAW_DELAY_FRAMES = 10  
frames_in_draw_pose = 0

all_strokes = []  # Stores completed lines (pen lifted)
current_path = [] # Stores the active line (pen down)

# --- 3. DATA SAVING FUNCTION ---
def save_stroke_to_csv(stroke, label):
    if len(stroke) < 10:
        print("Stroke too short to save!")
        return

    # Normalization: Make the first coordinate exactly (0,0)
    start_x, start_y = stroke[0]
    normalized_stroke = []
    for x, y in stroke:
        normalized_stroke.append((x - start_x, y - start_y))
    
    # Flatten the list of tuples into a single line of numbers so it fits in a CSV
    # Example: [x1, y1, x2, y2, x3, y3...]
    flat_data = [label] # First column is the letter name
    for point in normalized_stroke:
        flat_data.extend(point)

    # Append to the CSV file
    file_exists = os.path.isfile('dataset.csv')
    with open('dataset.csv', mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(flat_data)
    
    print(f"✅ Saved letter: '{label.upper()}' (Length: {len(stroke)} frames)")


# --- 4. THE INGESTION LOOP ---
cap = cv2.VideoCapture(0)

with mp_hands.Hands(
    model_complexity=0,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5) as hands:
    
    print("DATA COLLECTION MODE STARTED!")
    
    while cap.isOpened():
        success, image = cap.read()
        if not success: continue

        image = cv2.flip(image, 1) 
        image_height, image_width, _ = image.shape
        
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb_image)

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                
                index_tip = hand_landmarks.landmark[8]
                index_knuckle = hand_landmarks.landmark[5]
                middle_tip = hand_landmarks.landmark[12]
                middle_knuckle = hand_landmarks.landmark[9]

                cx = int(index_tip.x * image_width)
                cy = int(index_tip.y * image_height)
                
                is_drawing_pose = (index_tip.y < index_knuckle.y) and (middle_tip.y > middle_knuckle.y)
                
                if is_drawing_pose:
                    frames_in_draw_pose += 1
                    
                    if frames_in_draw_pose > DRAW_DELAY_FRAMES:
                        # Pen is DOWN: Add to the active line
                        current_path.append((cx, cy))
                    else:
                        cv2.circle(image, (cx, cy), 10, (0, 255, 255), cv2.FILLED)
                else:
                    # Pen is UP: The user closed their fist. 
                    # If they were just drawing, save that line to all_strokes and clear the active path!
                    if len(current_path) > 0:
                        all_strokes.append(current_path)
                        current_path = []
                        
                    frames_in_draw_pose = 0
                    cv2.circle(image, (cx, cy), 10, (0, 0, 255), cv2.FILLED)

        # --- DRAWING ALL THE INK TO THE SCREEN ---
        # 1. Draw the permanently saved strokes
        for stroke in all_strokes:
            for i in range(1, len(stroke)):
                cv2.line(image, stroke[i-1], stroke[i], (0, 255, 0), 4)
                
        # 2. Draw the active path currently being drawn
        for i in range(1, len(current_path)):
            cv2.line(image, current_path[i-1], current_path[i], (0, 255, 0), 4)

        # --- KEYBOARD LISTENER ---
        key = cv2.waitKey(5) & 0xFF
        if key == 27: 
            break
        elif key == 32: # SPACEBAR clears the screen
            all_strokes = []
            current_path = []
            frames_in_draw_pose = 0
            print("Cleared screen.")
        elif key < 128: # If any standard keyboard key is pressed
            char_pressed = chr(key).lower()
            
            # We now explicitly allow letters, numbers, and math operators
            valid_chars = "abcdefghijklmnopqrstuvwxyz0123456789+-*/="
            
            if char_pressed in valid_chars:
                # Combine all strokes and the current path into one flat list
                full_letter_coordinates = []
                for stroke in all_strokes:
                    full_letter_coordinates.extend(stroke)
                full_letter_coordinates.extend(current_path)
                
                save_stroke_to_csv(full_letter_coordinates, char_pressed)
                
                # Wipe the whiteboard clean for the next drawing
                all_strokes = []
                current_path = []
                frames_in_draw_pose = 0
            
        elif key == 32: 
            all_strokes = []
            current_path = []
            frames_in_draw_pose = 0
            print("Cleared screen.")

        cv2.imshow('Air Canvas - Data Collector', image)

cap.release()
cv2.destroyAllWindows()