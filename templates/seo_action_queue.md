# Prioritized SEO & Conversion Action Queue

**Site:** `{{ site }}`  
**Generated:** `{{ generated_at }}`  
**Total Actions:** `{{ total_actions }}`  

---

## Executive Opportunity Summary

| Detector Category | Count | Potential Incremental Clicks | Expected Incremental Value |
| :--- | :--- | :--- | :--- |
| **CTR Improvement** | `{{ actions_by_type.ctr_improvement }}` | `{{ totals.ctr_clicks }}` | `${{ totals.ctr_val }}` |
| **Ranking Opportunity** | `{{ actions_by_type.ranking_opportunity }}` | `{{ totals.rank_clicks }}` | `${{ totals.rank_val }}` |
| **Conversion Leakage** | `{{ actions_by_type.conversion_leakage }}` | — | `${{ totals.cro_val }}` |
| **Technical Risk** | `{{ actions_by_type.technical_risk }}` | `{{ totals.tech_clicks }}` | `${{ totals.tech_val }}` |
| **Content Expansion** | `{{ actions_by_type.content_expansion_or_consolidation }}` | `{{ totals.expansion_clicks }}` | `${{ totals.expansion_val }}` |

---

## Action Queue Backlog

| Rank | Action ID | Type | Target URL | Direct Data Observation | Proposed Action | Expected Impact | Confidence |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{% for a in actions %}
| **{{ loop.index }}** | `{{ a.action_id }}` | `{{ a.opportunity_type }}` | `{{ a.target_urls[0] }}` | {{ a.direct_observation }} | {{ a.proposed_action }} | ${{ a.expected_impact.expected_incremental_value }} | {{ a.confidence }} |
{% endfor %}

---

## Action Execution Cards

{% for a in actions %}
### [`{{ a.action_id }}`] {{ a.proposed_action }}

- **Direct Data Observation:** {{ a.direct_observation }}
- **Target URLs:** `{{ a.target_urls | join(', ') }}`
- **Opportunity Type:** `{{ a.opportunity_type }}`
- **Priority Score:** **{{ a.priority_score }}** (Confidence: `{{ a.confidence }}`, Effort: `{{ a.effort }}`, Risk: `{{ a.risk }}`)
- **Hypothesis:** {{ a.hypothesis }}
- **Evaluation Methodology:** `{{ a.experiment_method }}`
- **Observed Evidence:**
{% for ev in a.evidence_details %}
  - `[{{ ev.source | upper }}]` {{ ev.observation }}
{% endfor %}

---
{% endfor %}
