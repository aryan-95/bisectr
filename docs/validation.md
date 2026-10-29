# Repeatable service validation

The existing evaluation harness measures injected regressions on the demo service. To measure a
service you control, build baseline and candidate container images, push them to the configured ECR
repository, and define a scenario in `bisectr.yaml` that matches the service's normal request mix.
Use a staging deployment or disposable data: the configured HTTP methods and JSON bodies are sent to
each probe image.

For example, after pushing both images to ECR (prefer immutable SHA tags or image digests):

```bash
bisectr validate \
  --config bisectr.yaml \
  --baseline BASELINE_IMAGE_TAG \
  --candidate CANDIDATE_IMAGE_TAG \
  --trials 5 \
  --out eval/service-validation.csv
```

Use the full image URI instead of a tag when the images are in different repositories. Each trial
disables baseline caching and launches baseline and candidate replicas together. The CSV records the
verdict, p95 ratio, statistical p-value, replica agreement, cost-regression flag, and elapsed time.
Individual trials are also saved as local or DynamoDB run records, and can be inspected with
`bisectr trends --kind validate`.

Before accepting a result:

1. Run a control comparison using the same image on both sides. Repeat it enough times to observe
   the false-positive rate under the selected workload.
2. Compare known-good and known-regressed images. A known regression should be specified in advance
   and reproduced in a staging environment.
3. Record the scenario profile, image digests, region, task sizing, trial count, verdicts, runtimes,
   and estimated AWS spend alongside the CSV.
4. Treat `WARN` as inconclusive, not as evidence that the images are equivalent. Investigate noisy
   trials rather than excluding them after seeing the result.
5. Do not send write requests to production data. The runner is designed for containerized HTTP
   services but does not provide production traffic isolation or data anonymization.

Example weighted request mix:

```yaml
scenario:
  profile: checkout-staging
  rps: 20
  seconds: 60
  warmup_seconds: 10
  endpoints:
    - {path: /users, weight: 3}
    - {path: /orders, weight: 2, method: POST, body: {items: [{sku: demo, quantity: 1}]}}
```

The POST example is safe only when the target service is configured to accept disposable test data.
Keep credentials out of endpoint definitions; the probe tasks intentionally have no task role and the
current configuration does not support secret injection into requests.

`bisectr validate` is a measurement tool, not proof of production impact. This repository still
requires an owner-supplied service and measured trials before it can claim validation on a
third-party or production service.
