import csv
import random

# --- 1. CONFIGURATION ---
INPUT_FILE = 'dataset.csv'
OUTPUT_FILE = 'augmented_dataset.csv'
COPIES_PER_SAMPLE = 50  # Turns 20 drawings into 1,000!

# --- 2. AUGMENTATION MATH ---
def augment_coordinates(coords):
    augmented = []
    
    # Generate random stretching factors (e.g., 0.8 means 20% compressed, 1.2 means 20% stretched)
    scale_x = random.uniform(0.8, 1.2)
    scale_y = random.uniform(0.8, 1.2)
    
    for i in range(0, len(coords), 2):
        x = coords[i]
        y = coords[i+1]
        
        # Add random "hand shake" noise between -5 and +5 pixels
        noise_x = random.uniform(-5.0, 5.0)
        noise_y = random.uniform(-5.0, 5.0)
        
        # Apply the transformations
        new_x = (x * scale_x) + noise_x
        new_y = (y * scale_y) + noise_y
        
        # Force the very first coordinate to stay exactly at (0,0) to keep normalization
        if i == 0:
            new_x, new_y = 0.0, 0.0
            
        augmented.extend([new_x, new_y])
        
    return augmented

# --- 3. DATA PROCESSING PIPELINE ---
print(f"Reading original data from {INPUT_FILE}...")

total_original = 0
total_generated = 0

with open(INPUT_FILE, 'r') as infile, open(OUTPUT_FILE, 'w', newline='') as outfile:
    reader = csv.reader(infile)
    writer = csv.writer(outfile)
    
    for row in reader:
        if not row: continue
        total_original += 1
        
        label = row[0]
        # Convert the string coordinates back into floats
        coords = [float(val) for val in row[1:]]
        
        # 1. Always save the exact original drawing
        writer.writerow(row)
        total_generated += 1
        
        # 2. Generate and save the synthetic mutations
        for _ in range(COPIES_PER_SAMPLE):
            mutated_coords = augment_coordinates(coords)
            
            # Combine label and mutated coordinates into one flat list
            new_row = [label] + mutated_coords
            writer.writerow(new_row)
            total_generated += 1

print("✅ Data Augmentation Complete!")
print(f"Original samples: {total_original}")
print(f"New dataset size: {total_generated} samples saved to '{OUTPUT_FILE}'")