#!/usr/bin/env bash
# deploy.sh — Deploy SiteGuard AI to Google Cloud Run
# Usage: ./deploy.sh <GCP_PROJECT_ID> [REGION]
# Example: ./deploy.sh siteguard-789 us-central1
set -euo pipefail

PROJECT_ID="${1:?Usage: ./deploy.sh <GCP_PROJECT_ID> [REGION]}"
REGION="${2:-us-central1}"
BACKEND_SERVICE="siteguard-backend"
FRONTEND_SERVICE="siteguard-frontend"

echo "🚀 Deploying SiteGuard AI to project: $PROJECT_ID, region: $REGION"

# ─── Authenticate & set project ──────────────────────────────────────────────
gcloud config set project "$PROJECT_ID"

# ─── Enable required APIs ─────────────────────────────────────────────────────
echo "📦 Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  containerregistry.googleapis.com \
  firestore.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  --project="$PROJECT_ID"

# ─── Store secrets in Secret Manager ─────────────────────────────────────────
echo "🔐 Storing secrets in Secret Manager..."
echo "Enter your Gemini API key:"
read -rs GEMINI_KEY
echo -n "$GEMINI_KEY" | gcloud secrets create GEMINI_API_KEY \
  --data-file=- --replication-policy=automatic --project="$PROJECT_ID" 2>/dev/null || \
  echo -n "$GEMINI_KEY" | gcloud secrets versions add GEMINI_API_KEY \
  --data-file=- --project="$PROJECT_ID"

# Bucket names as secrets (optional, can hardcode)
echo -n "siteguard-evidence" | gcloud secrets create GCS_BUCKET_EVIDENCE \
  --data-file=- --replication-policy=automatic --project="$PROJECT_ID" 2>/dev/null || true
echo -n "siteguard-reports" | gcloud secrets create GCS_BUCKET_REPORTS \
  --data-file=- --replication-policy=automatic --project="$PROJECT_ID" 2>/dev/null || true
echo -n "siteguard-recordings" | gcloud secrets create GCS_BUCKET_RECORDINGS \
  --data-file=- --replication-policy=automatic --project="$PROJECT_ID" 2>/dev/null || true

# ─── Build & deploy backend ───────────────────────────────────────────────────
echo "🔨 Building backend image..."
gcloud builds submit ./backend \
  --tag="gcr.io/$PROJECT_ID/$BACKEND_SERVICE" \
  --project="$PROJECT_ID"

echo "🚢 Deploying backend to Cloud Run..."
gcloud run deploy "$BACKEND_SERVICE" \
  --image="gcr.io/$PROJECT_ID/$BACKEND_SERVICE" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=10 \
  --set-env-vars="ENVIRONMENT=production,GCP_PROJECT_ID=$PROJECT_ID,GCP_REGION=$REGION" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,GCS_BUCKET_EVIDENCE=GCS_BUCKET_EVIDENCE:latest,GCS_BUCKET_REPORTS=GCS_BUCKET_REPORTS:latest,GCS_BUCKET_RECORDINGS=GCS_BUCKET_RECORDINGS:latest" \
  --service-account="siteguard-backend@$PROJECT_ID.iam.gserviceaccount.com" \
  --project="$PROJECT_ID"

# ─── Get backend URL ──────────────────────────────────────────────────────────
BACKEND_URL=$(gcloud run services describe "$BACKEND_SERVICE" \
  --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')
BACKEND_WS_URL=$(echo "$BACKEND_URL" | sed 's/https/wss/')

echo "✅ Backend deployed: $BACKEND_URL"

# ─── Build & deploy frontend ──────────────────────────────────────────────────
echo "🔨 Building frontend image with backend URL: $BACKEND_URL"
gcloud builds submit ./frontend \
  --tag="gcr.io/$PROJECT_ID/$FRONTEND_SERVICE" \
  --build-arg="VITE_BACKEND_API_URL=$BACKEND_URL" \
  --build-arg="VITE_BACKEND_WS_URL=$BACKEND_WS_URL" \
  --project="$PROJECT_ID"

echo "🚢 Deploying frontend to Cloud Run..."
gcloud run deploy "$FRONTEND_SERVICE" \
  --image="gcr.io/$PROJECT_ID/$FRONTEND_SERVICE" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --port=3000 \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=5 \
  --project="$PROJECT_ID"

FRONTEND_URL=$(gcloud run services describe "$FRONTEND_SERVICE" \
  --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')

echo ""
echo "════════════════════════════════════════"
echo "✅ SiteGuard AI deployed successfully!"
echo "   Frontend: $FRONTEND_URL"
echo "   Backend:  $BACKEND_URL"
echo "════════════════════════════════════════"
