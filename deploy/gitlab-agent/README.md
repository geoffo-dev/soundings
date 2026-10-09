# GitLab agent for Kubernetes (Soundings' deploys)

The GitLab pipeline deploys through the GitLab agent for Kubernetes: agentk runs in the
cluster and connects out to GitLab's agent server (KAS); deploy jobs get a short-lived
kubeconfig context through that connection. GitLab stores no cluster credential, and the
cluster accepts no inbound connection. One agent per environment, each allowed into its
Soundings namespace only. The full walkthrough, with the CI/CD variables and the project
settings, is in [docs/operator-guide.md, "Continuous delivery"](../../docs/operator-guide.md#continuous-delivery-phase-9).

| File | What it is |
|---|---|
| [`../environments/cluster-setup.yaml`](../environments/cluster-setup.yaml) | The namespaces and the `soundings-deployer` ClusterRole (namespaced rules) |
| [`rbac.yaml`](rbac.yaml) | The agents' namespaces, agentk's Lease/Events Role, and `soundings-deployer` bound in `soundings-<env>` to each agent's ServiceAccount |
| [`values.yaml`](values.yaml) | Values for GitLab's `gitlab-agent` chart from your mirror: `rbac.create=false`, no container scanning, the token from a Secret |
| [`../../.gitlab/agents/soundings-*/config.yaml`](../../.gitlab/agents/) | Each agent's `ci_access`: this project only, its environment only, production on protected refs only |

Install order (an operator with cluster-admin, once per cluster):

1. GitLab serves **https**, including the agent server (`/-/kubernetes-agent/`):
   kubectl and Helm send the job's credentials only over TLS.
2. `kubectl apply -f deploy/environments/cluster-setup.yaml -f deploy/gitlab-agent/rbac.yaml`
3. Edit both `.gitlab/agents/soundings-*/config.yaml` to name this project's full path
   and merge to the default branch.
4. Register the agents (Operate > Kubernetes clusters > Connect a cluster, names
   `soundings-staging` and `soundings-production`) and keep each token:
   `kubectl -n gitlab-agent-staging create secret generic soundings-staging-agent-token --from-literal=token=<token>`
   (and the same for production).
5. Mirror the chart and the agentk image, then install it twice (`values.yaml` has the
   command), with `--set-file config.kasCaCert=<internal CA>` when GitLab's certificate
   comes from an internal CA.
6. Check: **Operate > Kubernetes clusters** shows both agents connected; then
   `kubectl auth can-i --list -n soundings-production --as=system:serviceaccount:gitlab-agent-staging:soundings-staging-agent`
   shows nothing beyond what every account may do.
