#!/usr/bin/env bash
#
# Put a new S3 access key into local_settings.py without it appearing in a
# shell history, a log, or a chat transcript.
#
#   ./deploy/set-s3-key.sh
#
# Prompts for the key id and secret (the secret is not echoed), rewrites the
# two lines in stickersheet/local_settings.py, reloads the app and checks that
# the new key can actually read and write the bucket.
#
# Do this BEFORE deactivating the old key in IAM. The running site needs
# working credentials for every page render — existence checks on derivative
# files go through the S3 API — so revoking first takes the gallery down.

set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS="$PROJECT/stickersheet/local_settings.py"
PY="$PROJECT/.venv/bin/python"

[[ -f "$SETTINGS" ]] || { echo "no local_settings.py at $SETTINGS" >&2; exit 1; }

read -r -p "AWS_ACCESS_KEY_ID: " KEY_ID
read -r -s -p "AWS_SECRET_ACCESS_KEY (not echoed): " KEY_SECRET
echo

[[ -n "$KEY_ID" && -n "$KEY_SECRET" ]] || { echo "both values are required" >&2; exit 1; }

# Check the new key before writing it anywhere.
echo "Testing the new key against the bucket..."
if ! AWS_TEST_KEY="$KEY_ID" AWS_TEST_SECRET="$KEY_SECRET" "$PY" - <<'PYEOF'
import os, sys
import boto3
from botocore.exceptions import ClientError
s3 = boto3.client('s3', region_name='us-east-1',
                  aws_access_key_id=os.environ['AWS_TEST_KEY'],
                  aws_secret_access_key=os.environ['AWS_TEST_SECRET'])
B = 'dipstick.earth'
try:
    s3.put_object(Bucket=B, Key='media/__keycheck__', Body=b'ok')
    s3.get_object(Bucket=B, Key='media/__keycheck__')
    s3.delete_object(Bucket=B, Key='media/__keycheck__')
except ClientError as e:
    print('  FAILED: %s' % e.response['Error']['Code'])
    sys.exit(1)
print('  read/write/delete on media/ all OK')
PYEOF
then
    echo "New key does not work — nothing changed." >&2
    exit 1
fi

cp -a "$SETTINGS" "$SETTINGS.bak"
KEY_ID="$KEY_ID" KEY_SECRET="$KEY_SECRET" "$PY" - "$SETTINGS" <<'PYEOF'
import os, re, sys
path = sys.argv[1]
s = open(path).read()
s = re.sub(r"^AWS_ACCESS_KEY_ID = '.*'$",
           "AWS_ACCESS_KEY_ID = '%s'" % os.environ['KEY_ID'], s, flags=re.M)
s = re.sub(r"^AWS_SECRET_ACCESS_KEY = '.*'$",
           "AWS_SECRET_ACCESS_KEY = '%s'" % os.environ['KEY_SECRET'], s, flags=re.M)
open(path, 'w').write(s)
PYEOF

# local_settings.py must stay readable by apache, or every request 500s.
chgrp www-data "$SETTINGS" 2>/dev/null || true
chmod 640 "$SETTINGS"
rm -f "$SETTINGS.bak"

touch "$PROJECT/stickersheet/wsgi.py"
echo "Written and app reloaded. Waiting for the daemon..."
sleep 5

for path in / /gallery/ /api/stickers/; do
    printf '  %-18s %s\n' "$path" \
        "$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 "https://dipstick.earth$path")"
done

echo
echo "If those are all 200, NOW deactivate the old key in IAM:"
echo "  aws iam update-access-key --user-name dipstick \\"
echo "      --access-key-id AKIAWWJV6K7E64NFIHOS --status Inactive"
echo "  # then, once you are happy:"
echo "  aws iam delete-access-key --user-name dipstick --access-key-id AKIAWWJV6K7E64NFIHOS"
