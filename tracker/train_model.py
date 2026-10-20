import csv
import pickle
import numpy as np
from sklearn.ensemble import RandomForestClassifier

print("Loading dataset...")
X, y = [], []
max_length = 0

# 1. Read the raw coordinate data
with open('augmented_dataset.csv', 'r') as f:
    reader = csv.reader(f)
    for row in reader:
        if not row: continue
        label = row[0]
        # Convert strings to floats
        coords = [float(val) for val in row[1:]] 
        max_length = max(max_length, len(coords))
        X.append(coords)
        y.append(label)

# 2. Pad the data (Machine Learning requires uniform matrix sizes)
for i in range(len(X)):
    # Fill shorter drawings with zeros so they match the longest drawing
    X[i].extend([0.0] * (max_length - len(X[i])))

X = np.array(X)
y = np.array(y)

# 3. Train the Model
print(f"Training Random Forest AI on {len(X)} samples...")
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X, y)

# 4. Save the Model and the padding length
print("Saving model to disk...")
with open('gesture_model.pkl', 'wb') as f:
    pickle.dump({'model': model, 'max_length': max_length}, f)
    
print("Done! Your custom AI brain is ready.")