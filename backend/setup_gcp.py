"""
SiteGuard AI — One-time GCP Setup Script
Run this ONCE to create all required GCP resources.

Usage:
    python setup_gcp.py

Requirements:
    pip install google-cloud-storage google-cloud-bigquery google-cloud-firestore
    gcloud auth application-default login   # OR set GOOGLE_APPLICATION_CREDENTIALS
"""

import sys
import json
from datetime import datetime

# ─── Load .env ────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()
import os

PROJECT_ID    = os.getenv("GCP_PROJECT_ID", "siteguard-789")
REGION        = os.getenv("GCP_REGION", "us-central1")
BUCKET_EVD    = os.getenv("GCS_BUCKET_EVIDENCE", "siteguard-evidence")
BUCKET_RPT    = os.getenv("GCS_BUCKET_REPORTS",  "siteguard-reports")
BUCKET_REC    = os.getenv("GCS_BUCKET_RECORDINGS","siteguard-recordings")
BQ_DATASET    = "siteguard"

print(f"\n🛡️  SiteGuard AI — GCP Setup")
print(f"   Project: {PROJECT_ID}")
print(f"   Region:  {REGION}\n")

errors = []

# ─── 1. Cloud Storage Buckets ─────────────────────────────────────────────────
from google.cloud import storage

def create_bucket(name: str, desc: str):
    client = storage.Client(project=PROJECT_ID)
    try:
        bucket = client.bucket(name)
        if client.lookup_bucket(name):
            print(f"   ✓ Bucket already exists: {name}")
        else:
            new_bucket = client.create_bucket(bucket, location=REGION)
            # Enforce uniform bucket-level access (no public ACLs)
            new_bucket.iam_configuration.uniform_bucket_level_access_enabled = True
            new_bucket.patch()
            print(f"   ✅ Created bucket: {name}  ({desc})")
    except Exception as e:
        print(f"   ❌ Bucket {name} failed: {e}")
        errors.append(str(e))

print("📦 Creating Cloud Storage buckets...")
create_bucket(BUCKET_EVD, "evidence frames")
create_bucket(BUCKET_RPT, "compliance reports")
create_bucket(BUCKET_REC, "uploaded recordings")

# ─── 2. BigQuery Dataset + Table ──────────────────────────────────────────────
from google.cloud import bigquery

print("\n📊 Creating BigQuery dataset...")
bq = bigquery.Client(project=PROJECT_ID)
dataset_id = f"{PROJECT_ID}.{BQ_DATASET}"

try:
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = REGION
    bq.create_dataset(dataset, exists_ok=True)
    print(f"   ✅ Dataset ready: {BQ_DATASET}")
except Exception as e:
    print(f"   ❌ Dataset failed: {e}")
    errors.append(str(e))

VIOLATIONS_SCHEMA = [
    bigquery.SchemaField("id",               "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("session_id",       "STRING"),
    bigquery.SchemaField("camera_id",        "STRING"),
    bigquery.SchemaField("site_id",          "STRING"),
    bigquery.SchemaField("timestamp",        "TIMESTAMP"),
    bigquery.SchemaField("violation_type",   "STRING"),
    bigquery.SchemaField("description",      "STRING"),
    bigquery.SchemaField("osha_code",        "STRING"),
    bigquery.SchemaField("severity",         "STRING"),
    bigquery.SchemaField("remediation",      "STRING"),
    bigquery.SchemaField("confidence",       "FLOAT"),
    bigquery.SchemaField("evidence_image_url","STRING"),
]
try:
    table_id = f"{dataset_id}.violations"
    table = bigquery.Table(table_id, schema=VIOLATIONS_SCHEMA)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="timestamp"
    )
    bq.create_table(table, exists_ok=True)
    print(f"   ✅ Table ready: violations (partitioned by day)")
except Exception as e:
    print(f"   ❌ Table failed: {e}")
    errors.append(str(e))

# ─── 3. Firestore — Seed Demo Site ───────────────────────────────────────────
from google.cloud import firestore

print("\n🔥 Seeding Firestore demo site...")
try:
    db = firestore.Client(project=PROJECT_ID)

    # Create demo site
    db.collection("sites").document("demo-site").set({
        "id":           "demo-site",
        "name":         "Main Construction Site",
        "address":      "123 Build St, New York, NY 10001",
        "manager_ids":  [],
        "camera_ids":   [],
        "risk_score":   0.0,
        "is_active":    True,
        "created_at":   datetime.utcnow().isoformat(),
    }, merge=True)
    print("   ✅ Demo site created: demo-site")

    # Create a sample supervisor phone camera
    db.collection("cameras").document("cam-phone-supervisor").set({
        "id":                   "cam-phone-supervisor",
        "site_id":              "demo-site",
        "name":                 "Supervisor Phone",
        "mode":                 "phone",
        "stream_url":           None,
        "status":               "offline",
        "location_description": "Roving supervisor camera",
        "is_active":            True,
        "created_at":           datetime.utcnow().isoformat(),
    }, merge=True)
    print("   ✅ Supervisor phone camera seeded")

    # Create a sample IP camera (you can update RTSP URL later)
    db.collection("cameras").document("cam-ip-main-gate").set({
        "id":                   "cam-ip-main-gate",
        "site_id":              "demo-site",
        "name":                 "Main Gate IP Camera",
        "mode":                 "ip_camera",
        "stream_url":           "rtsp://your-camera-ip:554/stream",   # ← update this
        "status":               "offline",
        "location_description": "Main site entrance",
        "is_active":            False,  # Enable after updating RTSP URL
        "created_at":           datetime.utcnow().isoformat(),
    }, merge=True)
    print("   ✅ IP camera seeded (disabled — update RTSP URL to activate)")

except Exception as e:
    print(f"   ❌ Firestore seeding failed: {e}")
    errors.append(str(e))

# ─── Summary ──────────────────────────────────────────────────────────────────
print("\n" + "─" * 50)
if errors:
    print(f"⚠️  Setup completed with {len(errors)} error(s):")
    for e in errors:
        print(f"   • {e}")
    print("\nPlease run: gcloud auth application-default login")
    print("Then re-run this script.")
else:
    print("🎉 All resources created successfully!")
    print(f"""
Next steps:
  1. python main.py                   # Start backend at http://localhost:8080
  2. Open http://localhost:3000        # Frontend already running
  3. Swagger docs at http://localhost:8080/docs
""")

print("─" * 50)
