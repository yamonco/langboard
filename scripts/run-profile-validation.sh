#!/usr/bin/env bash
set -eu

profile=${PROFILE:?PROFILE is required}
mkdir -p /result/artifacts

case "$profile" in
  api)
    export PROJECT_NAME="${PROJECT_NAME:-langboard}"
    command=(uv run --no-sync pytest -q --junitxml=/result/artifacts/api.xml \
      src/api/tests/runtime/test_app.py \
      src/api/langboard/routes/board/BoardCardApi_authority_test.py \
      src/api/tests/mcp_integration/test_card_mcp_contract.py \
      src/api/tests/card_visibility/test_visibility_transition.py \
      src/api/tests/card_visibility/test_policy.py \
      src/api/tests/card_visibility/test_private_policy.py)
    ;;
  worker)
    command=(uv run --no-sync pytest -q --junitxml=/result/artifacts/worker.xml \
      src/shared/py/langboard_shared/tasks/docling/DocumentVision_test.py \
      src/shared/py/langboard_shared/tasks/docling/DocumentKeywords_test.py)
    ;;
  ui)
    command=(bash -c 'yarn test:socket-runtime && yarn test:asset-retention')
    ;;
  *)
    echo "Unsupported validation profile: $profile" >&2
    exit 2
    ;;
esac

status=0
if ("${command[@]}") >"/result/artifacts/${profile}-validation.log" 2>&1; then
  status=0
else
  status=$?
fi

reports='[]'
if [[ -f "/result/artifacts/${profile}.xml" ]]; then
  reports="[\"artifacts/${profile}.xml\"]"
fi
printf '{"schemaVersion":1,"exitCode":%s,"reports":{"junit":%s,"artifacts":["artifacts/%s-validation.log"]}}\n' \
  "$status" "$reports" "$profile" > /result/result.json
# The result stage must complete so the central contract can inspect exitCode.
# Setup failures above still terminate the stage through `set -e`.
exit 0
