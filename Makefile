.RECIPEPREFIX = >
SHA := $(shell git rev-parse HEAD)
.PHONY: test push gate-ok gate-bad verify-fix eval history destroy
test:
> pytest -q
push:
> ./scripts/push_images.sh
gate-ok:
> bisectr gate --candidate $(SHA) --baseline $(SHA) --no-cache
gate-bad:
> bisectr gate --candidate $(SHA) --baseline $(SHA) --cand-env REGRESSION=slow_dependency --no-cache
verify-fix:
> bisectr verify-fix --baseline $(BASELINE) --candidate $(CANDIDATE)
eval:
> bisectr eval --image $(SHA) --trials 5 --bisect-trials 3
> python eval/report.py eval/results.csv
history:
> ./scripts/make_demo_history.sh 10 6
destroy:
> cd infra/envs/dev && terraform destroy
