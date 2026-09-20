"""Vastu weight calibration subsystem.

Calibrates rule weights w_r from practitioner pairwise judgments while keeping
modern_validity, treaties provenance, and non-negativity structural guarantees frozen.
"""

from .adapter import cards_from_corpus, observation_from_report, build_set, write_back
from .schema import CalibrationSet, PlanObservation, RuleCard, PairwiseJudgement
from .model import score, effective_weights, score_and_jacobian, normalise
from .fit import fit_pairwise, FitResult
from .design import select_pairs, coverage
from .validate import identifiable, bootstrap_weights, cross_validate, check_monotonicity, panel_agreement
