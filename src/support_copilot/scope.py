"""Deterministic corpus routing before retrieval and model verification."""

from dataclasses import dataclass
import re
from typing import Protocol


KUBERNETES_SCOPE_ROUTER_VERSION = "kubernetes_scope_v1"


@dataclass(frozen=True)
class ScopeRoute:
    """Describe which approved documentation corpus a question requires."""

    name: str
    display_name: str
    in_scope: bool


class ScopeRouter(Protocol):
    def route(self, question: str) -> ScopeRoute: ...


KUBERNETES_CORE = ScopeRoute(
    name="kubernetes_core",
    display_name="Kubernetes core",
    in_scope=True,
)


class KubernetesScopeRouter:
    """Fail closed for explicit dependencies absent from the pinned core corpus."""

    _ROUTES = (
        ("helm", "Helm", r"\bhelm(?:file)?\b|\bbitnami\b|\.values\b"),
        ("argocd", "Argo CD", r"\bargo\s*cd\b|\bargocd\b"),
        (
            "prometheus_ecosystem",
            "Prometheus ecosystem",
            r"\bprometheus(?:[- ](?:adapter|operator))\b|\bservicemonitors?\b|\bpodmonitors?\b",
        ),
        ("keda", "KEDA", r"\bkeda\b|\bscaledobjects?\b"),
        (
            "aws_eks",
            "AWS EKS",
            r"\b(?:amazon\s+)?eks\b|\baws-auth\b|\beksgettoken\w*\b",
        ),
        ("azure_aks", "Azure AKS", r"\b(?:azure\s+)?aks\b"),
        (
            "google_gke",
            "Google GKE",
            r"\b(?:google\s+)?gke\b|\bgoogle kubernetes engine\b",
        ),
        (
            "ingress_controller",
            "ingress-controller",
            r"\bingress[- ]nginx\b|\bnginx ingress controller\b|\btraefik\b",
        ),
        ("cert_manager", "cert-manager", r"\bcert-manager\b"),
        ("service_mesh", "service-mesh", r"\bistio\b|\blinkerd\b"),
        (
            "application_ecosystem",
            "application or vendor",
            r"\bspark structured streaming\b|\bhyperledger\b|\blocalstack\b|\bminio\b|\badvertised\.listeners\b",
        ),
    )

    def route(self, question: str) -> ScopeRoute:
        normalized = question.lower()
        for name, display_name, pattern in self._ROUTES:
            if re.search(pattern, normalized):
                return ScopeRoute(name=name, display_name=display_name, in_scope=False)
        return KUBERNETES_CORE


def router_for_tenant(tenant_id: str | None) -> ScopeRouter | None:
    """Return the production scope boundary configured for a tenant."""

    if tenant_id == "kubernetes":
        return KubernetesScopeRouter()
    return None
