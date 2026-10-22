# SEO & CRO Experiment Plan

## 1. Experiment Overview
- **Experiment ID:** `exp_{{ date }}_{{ slug }}`
- **Type:** `[ SEO Matched-Cohort | PostHog Visitor A/B Test ]`
- **Primary Hypothesis:** `{{ hypothesis }}`
- **Owner:** `{{ owner }}`
- **Launch Date:** `{{ launch_date }}`
- **Target Evaluation Date:** `{{ eval_date }} (28 days post-launch)`

---

## 2. Cohort & Variant Configuration

### For SEO Matched-Cohort Experiments:
| Cohort Group | URL Sample | Intervention Applied |
| :--- | :--- | :--- |
| **Treatment Group (10 URLs)** | `/path/to/treatment-1`, `/path/to/treatment-2`... | Modified title tag, injected H2, FAQPage schema. |
| **Control Group (10 URLs)** | `/path/to/control-1`, `/path/to/control-2`... | Unmodified baseline (zero template or metadata changes). |

### For PostHog Visitor-Level CRO Experiments:
| Variant | Traffic Split | Description of Client Experience |
| :--- | :--- | :--- |
| **Control (Variant A)** | 50% | Existing page layout and CTA copy. |
| **Challenger (Variant B)**| 50% | High-contrast sticky CTA button, simplified 2-field form. |

---

## 3. Metrics & Guardrails
- **Primary Metric:** `[ Incremental Organic Clicks | Signup Conversion Rate ]`
- **Secondary Metrics:** `[ Average Position | Time on Page | Organic Sessions ]`
- **Guardrail Metrics (Must Not Degrade):**
  - Core Web Vitals (LCP <= 2.5s, CLS <= 0.1, INP <= 200ms)
  - 5xx Server Error Rate (< 0.05%)
  - Overall Bounce Rate

---

## 4. Evaluation Criteria & Difference-in-Differences
$$\text{Net Treatment Lift} = (\text{Treatment}_{t1} - \text{Treatment}_{t0}) - (\text{Control}_{t1} - \text{Control}_{t0})$$

- **Win Condition:** Net Treatment Lift > +10% with $p < 0.05$.
- **Rollback Condition:** Net Treatment Lift < -5% or any critical guardrail breach.
