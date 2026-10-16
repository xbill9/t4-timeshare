curl -s localhost:8080/v1/chat/completions -H "Authorization: Bearer demo-key-B" \
  -d '{"messages":[{"role":"user","content":"Label this email: my parcel arrived broken"}],"max_tokens":20}' \
  | jq -c '{model, usage: .usage.total_tokens}'
curl -s localhost:8080/v1/chat/completions -H "Authorization: Bearer demo-key-C" \
  -d '{"messages":[{"role":"user","content":"Label this email: my parcel arrived broken"}],"max_tokens":20}' \
  | jq -c '{model, usage: .usage.total_tokens}'
curl -s localhost:8080/v1/chat/completions -H "Authorization: Bearer demo-key-B" \
  -d '{"model":"rand","messages":[{"role":"user","content":"hi"}]}' -w ' %{http_code}\n'
curl -s localhost:8080/v1/chat/completions -d '{"messages":[{"role":"user","content":"hi"}]}' -w ' %{http_code}\n'
tail -4 ledger.jsonl
