# Output formats, selectors & JSONPath (reference)

Most of kubectl's power for scripting and triage is in `-o` (how to print) and selectors (which objects).

## Output formats (`-o`)

| `-o` value | Use |
|---|---|
| *(default)* | The standard table |
| `wide` | Table + node, IP, nominated node, readiness |
| `name` | Just `kind/name` — great to pipe into another command |
| `yaml` / `json` | The full live object (includes status + managed fields) |
| `jsonpath='...'` | Extract specific fields (see below) |
| `jsonpath-file=f` | JSONPath template from a file |
| `custom-columns=...` | Define table columns from field paths |
| `custom-columns-file=f` | Columns from a file |
| `go-template='...'` / `go-template-file=f` | Full Go templating |
| `wide --show-labels` | Append a labels column |

```bash
kubectl get pods -o name | xargs -I{} kubectl delete {}        # name → pipe
kubectl get deploy my-service -o yaml | less                    # full spec
kubectl get pod my-pod -o json | jq '.status.containerStatuses' # pair with jq
```

## JSONPath recipes

`-o jsonpath` walks the object's JSON. Key syntax: `.` (child), `[*]` (all elements), `[?(@.x=="y")]`
(filter), `\n`/`\t` as literals, `{range}...{end}` to iterate.

```bash
# Image(s) of a deployment
kubectl get deploy my-service -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'

# Every pod name + its phase, one per line
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\n"}{end}'

# A pod's node
kubectl get pod my-pod -o jsonpath='{.spec.nodeName}{"\n"}'

# Names of pods that are NOT Running
kubectl get pods -o jsonpath='{range .items[?(@.status.phase!="Running")]}{.metadata.name}{"\n"}{end}'

# A Secret value (base64) → decode (mind exposure)
kubectl get secret app-secrets -o jsonpath='{.data.API_KEY}' | base64 -d

# Container env var names for a pod
kubectl get pod my-pod -o jsonpath='{.spec.containers[0].env[*].name}{"\n"}'

# The current context's default namespace
kubectl config view --minify -o jsonpath='{..namespace}{"\n"}'

# Wait on a custom condition with jsonpath
kubectl wait --for=jsonpath='{.status.phase}'=Running pod/my-pod --timeout=60s
```

## custom-columns & sorting

```bash
kubectl get pods -o custom-columns=\
NAME:.metadata.name,STATUS:.status.phase,NODE:.spec.nodeName,RESTARTS:.status.containerStatuses[0].restartCount

kubectl get pods --sort-by=.status.containerStatuses[0].restartCount   # noisiest first
kubectl get pods --sort-by=.metadata.creationTimestamp                 # oldest first
kubectl get events --sort-by=.lastTimestamp
```

Reuse a column set from a file with `-o custom-columns-file=cols.txt` (same `HEADER:.json.path` lines).

## go-template

`-o go-template` is the most powerful formatter (loops, conditionals, functions) for when JSONPath isn't
enough:

```bash
kubectl get pods -o go-template='{{range .items}}{{.metadata.name}}{{"\n"}}{{end}}'
kubectl get pods -o go-template-file=tmpl.gotmpl
```

Prefer `jsonpath` for simple field extraction; reach for `go-template` when you need conditionals or
formatting logic.

## Selectors

**Label selectors** (`-l` / `--selector`) — match on `metadata.labels`:

```bash
kubectl get pods -l app=my-service                       # equality
kubectl get pods -l 'env in (staging,prod)'              # set-based
kubectl get pods -l 'app=my-service,tier!=cache'         # AND + not-equal
kubectl get pods -l app                                  # has the label (any value)
kubectl delete pods -l app=my-service                    # acts on the matched set
```

**Field selectors** (`--field-selector`) — match on object fields (limited set per kind):

```bash
kubectl get pods --field-selector status.phase=Running
kubectl get pods --field-selector status.phase!=Running,spec.nodeName=node-1
kubectl get events --field-selector type=Warning
kubectl get pods --field-selector metadata.namespace=my-namespace
```

## Watching & follow

```bash
kubectl get pods -w                                      # stream changes (Ctrl-C to stop)
kubectl get pods -w -o wide -l app=my-service
kubectl logs -f deploy/my-service                        # follow logs
kubectl get events -w                                    # live events
```

## Handy combinations

```bash
# Restart-count leaderboard across the namespace
kubectl get pods -o custom-columns=NAME:.metadata.name,RESTARTS:.status.containerStatuses[0].restartCount \
  --sort-by=.status.containerStatuses[0].restartCount

# Images running in the namespace (dedup)
kubectl get pods -o jsonpath='{.items[*].spec.containers[*].image}' | tr ' ' '\n' | sort -u

# Delete all Failed pods
kubectl delete pods --field-selector status.phase=Failed
```
