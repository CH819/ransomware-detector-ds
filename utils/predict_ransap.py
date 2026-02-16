import sys
import pandas as pd
import joblib

# python utils/predict_ransap.py utils/data_set/ransap_training.csv
# ===============================
# CONFIG
# ===============================
MODEL_PATH = "utils/ransap_xgb_model.pkl"
SCALER_PATH = "utils/ransap_scaler.pkl"

OUTPUT_PATH = "utils/ransap_predictions.csv"


# ===============================
# LOAD MODEL + SCALER
# ===============================
print("Loading model...")

model = joblib.load(MODEL_PATH)
scaler = joblib.load(SCALER_PATH)


# ===============================
# INPUT FILE
# ===============================
if len(sys.argv) < 2:
    print("Usage: python predict_ransap.py input.csv")
    sys.exit(1)

input_file = sys.argv[1]

print("Loading data:", input_file)
df = pd.read_csv(input_file)


# ===============================
# FEATURE PREPARATION
# ===============================
X = df.drop(columns=["is_ransomware", "window_start"], errors="ignore")

X_scaled = scaler.transform(X)


# ===============================
# PREDICTION
# ===============================
print("Running inference...")

pred_labels = model.predict(X_scaled)
pred_probs = model.predict_proba(X_scaled)[:, 1]


# ===============================
# OUTPUT RESULTS
# ===============================
df["predicted_label"] = pred_labels
df["ransomware_probability"] = pred_probs

df.to_csv(OUTPUT_PATH, index=False)

print("Predictions saved to:", OUTPUT_PATH)


# ===============================
# SUMMARY
# ===============================
print("\nSummary:")
print(df["predicted_label"].value_counts())

print("\nAverage ransomware probability:",
      round(pred_probs.mean(), 4))
