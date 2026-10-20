import cv2
import mediapipe as mp
import pickle

# --- 1. LOAD THE TRAINED AI ---
try:
    with open('gesture_model.pkl', 'rb') as f:
        data = pickle.load(f)
        model = data['model']
        max_length = data['max_length']
except FileNotFoundError:
    print("Error: Run train_model.py first to generate gesture_model.pkl")
    exit()

# --- 2. PIPELINE SETUP ---
mp_hands = mp.solutions.hands
DRAW_DELAY_FRAMES = 10  
frames_in_draw_pose = 0
frames_in_pause_pose = 0

all_strokes = []
current_path = []

# --- 3. APPLICATION STATE ---
notebook_text = ""

cap = cv2.VideoCapture(0)

with mp_hands.Hands(
    model_complexity=0,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5) as hands:
    
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
                    frames_in_pause_pose = 0 # Reset pause timer
                    frames_in_draw_pose += 1
                    
                    if frames_in_draw_pose > DRAW_DELAY_FRAMES:
                        current_path.append((cx, cy))
                    else:
                        cv2.circle(image, (cx, cy), 10, (0, 255, 255), cv2.FILLED)
                else:
                    frames_in_draw_pose = 0
                    frames_in_pause_pose += 1
                    cv2.circle(image, (cx, cy), 10, (0, 0, 255), cv2.FILLED)
                    
                    # Watch the countdown in your terminal!
                    print(f"Fist held for: {frames_in_pause_pose} / 30 frames")
                    
                    # Lift Pen
                    if len(current_path) > 0:
                        # How many frames of the "tail" to delete
                        TAIL_TRIM = 8 
                        
                        # Only trim if the line is actually long enough
                        if len(current_path) > TAIL_TRIM:
                            cleaned_path = current_path[:-TAIL_TRIM] # Slices off the end
                        else:
                            cleaned_path = current_path
                            
                        all_strokes.append(cleaned_path)
                        current_path = []

                    # THE TRIGGER: If fist is held for ~1 second (30 frames)
                    if frames_in_pause_pose == 30:
                        if len(all_strokes) > 0:
                            print("🎯 TRIGGER HIT! Sending coordinates to AI...")
                            
                            # 1. Flatten all strokes
                            full_stroke = []
                            for stroke in all_strokes:
                                full_stroke.extend(stroke)
                                
                            # 2. Normalize to (0,0)
                            start_x, start_y = full_stroke[0]
                            normalized = []
                            for x, y in full_stroke:
                                normalized.extend([float(x - start_x), float(y - start_y)])
                                
                            # 3. Match matrix size
                            if len(normalized) > max_length:
                                normalized = normalized[:max_length]
                            else:
                                normalized.extend([0.0] * (max_length - len(normalized)))
                                
                            # 4. AI Prediction!
                            prediction = model.predict([normalized])[0]
                            print(f"🧠 AI Guessed: {prediction}")
                            
                            # 5. The Calculator Logic
                            if prediction == '=':
                                try:
                                    result = str(eval(notebook_text))
                                    notebook_text += f"={result}"
                                except Exception:
                                    notebook_text += "=ERROR"
                            else:
                                notebook_text += prediction
                            
                            all_strokes = []
                        else:
                            print("⚠️ Trigger hit, but no green ink was found!")

        # --- DRAWING RENDERING ---
        for stroke in all_strokes:
            for i in range(1, len(stroke)):
                cv2.line(image, stroke[i-1], stroke[i], (0, 255, 0), 4)
                
        for i in range(1, len(current_path)):
            cv2.line(image, current_path[i-1], current_path[i], (0, 255, 0), 4)

        # --- NOTEBOOK RENDERING ---
        cv2.putText(image, f"Notebook: {notebook_text}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)

        cv2.imshow('Smart Air Canvas', image)

        # --- KEYBOARD LISTENER ---
        key = cv2.waitKey(5) & 0xFF
        
        if key == 27: # ESC key to quit
            break
        elif key == 32: # SPACEBAR to completely clear the notebook
            notebook_text = ""
            all_strokes = []
            current_path = []
            print("Notebook cleared.")
        elif key == 8 or key == 127: # BACKSPACE / DELETE key
            if len(notebook_text) > 0:
                notebook_text = notebook_text[:-1] # Slices off the last character
                print(f"Backspace pressed. Notebook: {notebook_text}")

cap.release()
cv2.destroyAllWindows()