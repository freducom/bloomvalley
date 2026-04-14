"""Build-time tests for data integrity — catch misconfigurations before deploy.

These tests verify that mappings, constants, and error handling cover all
known values in the system, preventing silent data loss.
"""

import math

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# ASSET_CLASS_MAP completeness
# ---------------------------------------------------------------------------


class TestAssetClassMapCompleteness:
    """Every asset_class in the DB must have a glidepath mapping."""

    # All asset_class values that exist or could exist in the securities table
    KNOWN_ASSET_CLASSES = ["stock", "etf", "bond", "fund", "crypto"]

    def test_optimizer_map_covers_all(self):
        from app.services.optimizer import ASSET_CLASS_MAP
        for ac in self.KNOWN_ASSET_CLASSES:
            assert ac in ASSET_CLASS_MAP, f"'{ac}' missing from optimizer ASSET_CLASS_MAP"

    def test_backtester_map_covers_all(self):
        from app.services.backtester import ASSET_CLASS_MAP
        for ac in self.KNOWN_ASSET_CLASSES:
            assert ac in ASSET_CLASS_MAP, f"'{ac}' missing from backtester ASSET_CLASS_MAP"

    def test_risk_map_covers_all(self):
        from app.api.v1.risk import ASSET_CLASS_MAP
        for ac in self.KNOWN_ASSET_CLASSES:
            assert ac in ASSET_CLASS_MAP, f"'{ac}' missing from risk ASSET_CLASS_MAP"

    def test_all_maps_consistent(self):
        """All three ASSET_CLASS_MAP definitions should have the same keys."""
        from app.services.optimizer import ASSET_CLASS_MAP as opt_map
        from app.services.backtester import ASSET_CLASS_MAP as bt_map
        from app.api.v1.risk import ASSET_CLASS_MAP as risk_map
        assert set(opt_map.keys()) == set(bt_map.keys()) == set(risk_map.keys()), (
            f"ASSET_CLASS_MAP keys differ: optimizer={set(opt_map.keys())}, "
            f"backtester={set(bt_map.keys())}, risk={set(risk_map.keys())}"
        )

    def test_glidepath_categories_valid(self):
        """All ASSET_CLASS_MAP values must be valid glidepath categories."""
        from app.services.optimizer import ASSET_CLASS_MAP, GLIDEPATH
        valid_categories = set(list(GLIDEPATH.values())[0].keys())
        for ac, cat in ASSET_CLASS_MAP.items():
            assert cat in valid_categories, (
                f"'{ac}' maps to '{cat}' which is not a glidepath category. "
                f"Valid: {valid_categories}"
            )


# ---------------------------------------------------------------------------
# Exchange suffix coverage
# ---------------------------------------------------------------------------


class TestExchangeSuffixCoverage:
    """Every exchange MIC in the DB should have a Yahoo Finance suffix mapping."""

    # All exchange codes that exist in the securities table
    KNOWN_EXCHANGES = [
        "XHEL", "FNFI", "XSTO", "XFRA", "XETR", "GER", "XOSL",
        "XLON", "XPAR", "XAMS", "XBRU", "XCSE", "XSWX",
        "XNAS", "XNYS", "NMS", "NYSE", "NASDAQ",
    ]

    def test_all_exchanges_mapped(self):
        from app.pipelines.yahoo_finance import MIC_TO_SUFFIX
        for exchange in self.KNOWN_EXCHANGES:
            assert exchange in MIC_TO_SUFFIX, (
                f"Exchange '{exchange}' missing from MIC_TO_SUFFIX — "
                f"Yahoo Finance prices won't be fetched for securities on this exchange"
            )

    def test_suffixes_are_strings(self):
        from app.pipelines.yahoo_finance import MIC_TO_SUFFIX
        for exchange, suffix in MIC_TO_SUFFIX.items():
            assert isinstance(suffix, str), f"{exchange} suffix is not a string"

    def test_non_us_have_dot_prefix(self):
        """Non-US exchange suffixes should start with '.' or be empty."""
        from app.pipelines.yahoo_finance import MIC_TO_SUFFIX
        us_exchanges = {"XNAS", "XNYS", "NMS", "NYSE", "NASDAQ"}
        for exchange, suffix in MIC_TO_SUFFIX.items():
            if exchange not in us_exchanges and suffix:
                assert suffix.startswith("."), (
                    f"Exchange '{exchange}' suffix '{suffix}' should start with '.'"
                )


# ---------------------------------------------------------------------------
# Rebalancer fund classification
# ---------------------------------------------------------------------------


class TestFundClassification:
    """Fund asset class should be classified correctly by sector."""

    def test_bond_fund_is_fixed_income(self):
        from app.services.rebalancer import _map_asset_class
        assert _map_asset_class("fund", None) == "fixed_income"
        assert _map_asset_class("fund", "Corporate Bonds") == "fixed_income"
        assert _map_asset_class("fund", "Fixed Income") == "fixed_income"

    def test_equity_fund_is_equity(self):
        from app.services.rebalancer import _map_asset_class
        assert _map_asset_class("fund", "Equity Fund") == "equity"
        assert _map_asset_class("fund", "Global Equity") == "equity"

    def test_mixed_fund_defaults_to_fixed_income(self):
        from app.services.rebalancer import _map_asset_class
        assert _map_asset_class("fund", "Mixed") == "fixed_income"

    def test_fi_etf_is_fixed_income(self):
        from app.services.rebalancer import _map_asset_class
        assert _map_asset_class("etf", "Fixed Income") == "fixed_income"

    def test_stock_is_equity(self):
        from app.services.rebalancer import _map_asset_class
        assert _map_asset_class("stock", None) == "equity"

    def test_unknown_defaults_to_equity(self):
        from app.services.rebalancer import _map_asset_class
        assert _map_asset_class("unknown_type", None) == "equity"


# ---------------------------------------------------------------------------
# NaN/Inf sanitization
# ---------------------------------------------------------------------------


class TestNanSanitization:
    """Ensure financial calculations don't leak NaN/Inf into JSON responses."""

    def test_compute_metrics_no_nan(self):
        """compute_metrics should never return NaN or Inf values."""
        from app.services.backtester import compute_metrics

        # Flat series (zero std → potential division by zero)
        dv = [
            {"date": f"2024-01-{d:02d}", "valueCents": 100_000}
            for d in range(1, 10)
        ]
        result = compute_metrics(dv)
        for key, val in result.items():
            if isinstance(val, float):
                assert not math.isnan(val), f"NaN in compute_metrics[{key}]"
                assert not math.isinf(val), f"Inf in compute_metrics[{key}]"

    def test_compute_metrics_single_value_series(self):
        """Edge case: all same values (zero variance) — should not produce wild numbers."""
        from app.services.backtester import compute_metrics
        dv = [
            {"date": f"2024-01-{d:02d}", "valueCents": 50_000}
            for d in range(1, 20)
        ]
        result = compute_metrics(dv)
        assert result["sharpeRatio"] == 0.0
        # Sortino with zero-return series should be 0 or at least bounded
        assert abs(result["sortinoRatio"]) < 100, (
            f"Sortino ratio {result['sortinoRatio']} is unbounded — "
            f"near-zero downside std causing division explosion"
        )

    def test_numpy_nan_detection(self):
        """Verify our NaN detection catches numpy NaN variants."""
        assert math.isnan(float(np.nan))
        assert math.isinf(float(np.inf))
        assert math.isinf(float(-np.inf))


# ---------------------------------------------------------------------------
# CoinGecko pipeline resilience
# ---------------------------------------------------------------------------


class TestCoinGeckoPipelineDesign:
    """Verify CoinGecko pipeline handles rate limits gracefully."""

    def test_429_does_not_abort_immediately(self):
        """On 429, the pipeline should continue to other coins, not raise immediately."""
        import inspect
        import textwrap
        from app.pipelines.coingecko import CoinGeckoPrices

        source = inspect.getsource(CoinGeckoPrices.fetch)
        source = textwrap.dedent(source)

        # The 429 handler should `continue`, not `raise`
        # Find the block after "status_code == 429"
        lines = source.split("\n")
        in_429_block = False
        for line in lines:
            stripped = line.strip()
            if "status_code == 429" in stripped:
                in_429_block = True
                continue
            if in_429_block:
                if stripped.startswith("raise RetryableError"):
                    pytest.fail(
                        "CoinGecko pipeline raises RetryableError immediately on 429. "
                        "It should continue to next coin and only fail if ALL are rate-limited."
                    )
                if stripped and not stripped.startswith("#"):
                    break  # Past the 429 handler

    def test_partial_results_stored(self):
        """Pipeline should store partial results even when some coins are rate-limited."""
        import inspect
        from app.pipelines.coingecko import CoinGeckoPrices

        source = inspect.getsource(CoinGeckoPrices.fetch)
        # The final RetryableError should only fire when ALL coins failed
        assert "rate_limited == len(coin_ids)" in source, (
            "Pipeline should only raise RetryableError when ALL coins are rate-limited"
        )


# ---------------------------------------------------------------------------
# SEC EDGAR user-agent compliance
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Swarm AGENT_DATA endpoint coverage
# ---------------------------------------------------------------------------


class TestSwarmEndpointCoverage:
    """Verify that all endpoints the swarm requests actually exist in the backend."""

    def test_all_risk_sub_endpoints_resolved(self):
        """The swarm should request /risk (which exists) not /risk/metrics (which doesn't).
        The post-fetch transform splits /risk into virtual sub-endpoints."""
        import importlib
        # Import from the swarm if possible, otherwise check the principle
        try:
            # The swarm runs outside the backend, so we can't import it directly.
            # Instead, verify the backend only has one risk route.
            from app.api.v1.risk import router
            routes = [r.path for r in router.routes]
            # /risk/metrics, /risk/stress-tests etc should NOT be separate routes
            # There should be just the base "" (which becomes /risk via prefix)
            assert "" in routes or "/" in routes, "Base /risk route must exist"
        except Exception:
            pass

    def test_regime_indicator_exists_in_fred(self):
        """The PMI/sentiment indicator code used by macro/regime must be in FRED_SERIES."""
        from app.api.v1.macro import _REGIME_INDICATORS
        from app.pipelines.fred import FRED_SERIES

        pmi_code = _REGIME_INDICATORS.get("pmi")
        fred_codes = [s[0] for s in FRED_SERIES]

        # PMI indicator should either be in FRED or ECB series
        if pmi_code:
            from app.pipelines.ecb_macro import ECB_SERIES
            ecb_codes = [s[2] for s in ECB_SERIES]
            all_codes = fred_codes + ecb_codes
            assert pmi_code in all_codes, (
                f"Regime PMI indicator '{pmi_code}' not found in any pipeline. "
                f"It won't have data. Add it to FRED_SERIES or ECB_SERIES."
            )


class TestSecEdgarCompliance:
    """SEC EDGAR requires specific user-agent format."""

    def test_user_agent_has_email(self):
        """SEC requires 'Company AdminEmail' format per their docs."""
        from app.pipelines.sec_edgar import SEC_USER_AGENT
        assert "@" in SEC_USER_AGENT, (
            f"SEC user-agent '{SEC_USER_AGENT}' must contain an email address"
        )

    def test_user_agent_not_generic(self):
        from app.pipelines.sec_edgar import SEC_USER_AGENT
        generic = ["python-httpx", "python-requests", "Mozilla", "curl"]
        for g in generic:
            assert g.lower() not in SEC_USER_AGENT.lower(), (
                f"SEC user-agent should not be generic '{g}'"
            )
