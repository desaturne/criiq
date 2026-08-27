# Criiq — Viva Questions Only

Extracted from `docs/VIVA_QA.md` (questions only, no answers).

## 1. Project Overview, Motivation & Scope

- Q1. CRIIQ bhaneko ke ho ra cricket selection ma yesle kun specific problem solve garcha?
- Q2. Tapai le women's cricket lai primary focus kina garnu bhayo?
- Q2-follow-up. Yesto samasya cinha pachi, hamro project le tyo kasari solve garyo, ra hamro contribution ke ho?
- Q3. Existing cricket analytics systems ko comparison ma tapai ko project lai novel banaune kura ke ho?
- Q4. Yo system develop garnu ko main motivation ke thiyo?
- Q5. Tapai ko system traditional selector ko decision-making process bhanda kasari different cha?
- Q6. Tapai ko system ko target users ko hun ra kina?
- Q7. Tapai ko project ko main objectives ke-ke thiye?
- Q8. Tapai ko system le available cricket data ra actual player selection practice bich ko gap kasari address garcha?
- Q63. CRIIQ ko purpose selectors lai replace garnu ho ki decision-support provide garnu ho?

## 2. Data Pipeline & Sources

- Q9. Tapai ko data sources ke-ke hun ra harek source kina choose garnu bhayo?
- Q10. Multiple data sources bata aayeko data ko quality kasari ensure garnu bhayo?
- Q11. Different sources ma player identity resolution kasari handle garnu huncha?
- Q12. Tapai ko data pipeline ko overall structure kasto cha?
- Q13. Data pipeline lai idempotent ra safely re-run garna milne kasari ensure garnu huncha?
- Q14. Missing data, especially less-covered players ko case ma, kasari handle garnu huncha?
- Q15. Recent Form Index bhaneko ke ho ra yeslai kasari calculate garnu huncha?

## 3. Feature Engineering & Data Leakage

- Q16. Feature engineering garda data leakage kasari prevent garnu huncha?

## 4. Win-Probability-Added (WPA) — the Core Modeling Idea

- Q17. WPA bhaneko ke ho ra raw batting/bowling statistics ko satta WPA kina use garnu bhayo?
- Q18. WPA ko mathematical formula formulate garnus ra harek term explain garnus.
- Q19. Per-ball win probability kasari calculate garnu huncha?
- Q20. Batting ra bowling WPA lai separate targets ko rupma kina train garnu bhayo?
- Q21. Tapai ko WPA regression model le kun-kun features use garcha?
- Q22. HistGradientBoostingRegressor nai kina choose garnu bhayo?
- Q23. Different machine learning models lai kasari compare garnu bhayo?
- Q24. Temporal holdout bhaneko ke ho ra random train-test split ko satta yeslai kina use garnu bhayo?
- Q25. Tapai ko R² values 0.015 bhanda tala chan. Yeslai kasari justify garnu huncha?
- Q26. Pearson correlation R² bhanda tapai ko use case ma kina important cha?
- Q27. Brier score bhaneko ke ho ra yeslai kina use garnu huncha?
- Q28. Sign agreement accuracy le ke measure garcha ra yo kina important cha?
- Q29. A few matches bhayeka players ko lagi shrinkage ko role ke ho?
- Q30. Predicted vs. actual WPA plot lai kasari interpret garnu huncha?
- Q31. Residual plots le model ko bias ko barema ke information dincha?

## 5. The Composite Recommendation Score

- Q32. Tapai ko composite recommendation score ko seven components ke-ke hun?
- Q33. Model output matra use garnu ko satta composite score kina use garnu bhayo?
- Q34. Composite score ko weights kasari determine garnu bhayo?
- Q35. Matchup component bhaneko ke ho ra yeslai kasari calculate garnu huncha?
- Q36. Need component bhaneko ke ho ra yesle team balance kasari improve garcha?
- Q37. Risk penalties ke-ke hun ra kahile apply hunchan?
- Q38. Phase component bhaneko ke ho ra player ko best phase kasari identify garnu huncha?
- Q39. WPA model component lai 0–45 score ma kasari normalize garnu huncha?
- Q40. Composite score le raw WPA model bhanda better selection garcha bhanera kasari test garnu bhayo?

## 6. Playing XI Selection — Mixed-Integer Linear Programming (MILP)

- Q41. XI selection problem lai mathematically kasari formulate garnu huncha?
- Q42. Top 11 scores matra select garnu ko satta MILP kina use garnu bhayo?
- Q43. Legal playing XI ko lagi kun-kun constraints enforce garnu huncha?
- Q44. Insufficient qualifying players, Bhayeko pool lai kasari handle garnu huncha?
- Q45. MILP solver fail bhayo bhane ke huncha?
- Q46. Greedy repair fallback bhaneko ke ho ra kahile use huncha?
- Q47. MILP solver ko correctness kasari test garnu huncha?
- Q48. All-rounders jasto multiple roles fulfill garna sakne players lai kasari handle garnu huncha?

## 7. Genetic Algorithms — Bowling Rotation & Batting Order

- Q49. Genetic Algorithm le system ma ke optimize garcha?
- Q50. Bowling rotation GA le kaam garyo tara batting-order GA le kina garena?
- Q51. Genetic Algorithm ko convergence kasari evaluate garnu huncha?
- Q52. Bowling rotation problem ko solution kasari encode garnu huncha?
- Q53. Batting-order GA ko performance limitation kina bhayo?
- Q54. Batting-order GA lai improve garna ke garnu parcha?

## 8. Explainability — SHAP and GA Explanations

- Q55. SHAP explainability tapai ko system ma kasari work garcha?
- Q56. SHAP lai aru explainability methods bhanda kina choose garnu bhayo?
- Q57. SHAP explanations correct ra non-misleading chan bhanera kasari validate garnu huncha?
- Q58. Selectors ko lagi explainability kina important cha?

## 9. Technology Stack

- Q59. Python, FastAPI, React, SQLite, Parquet, and Joblib—jasto technology haru kina choose garnu bhayo?

## 10. Limitations, Deployment & Future Work

- Q60. Tapai ko system ko main limitations ke-ke hun?
- Q61. Future work ma tapai le ke-ke improve garna plan garnu bhayeko cha?
- Q62. Actual cricket board ma yo system kasari deploy garnu huncha?

## 11. Reflective Questions (for you to answer, grounded in real facts)

- Q64. Project ma tapai ko personal contribution ke thiyo?
- Q65. Tapai le project bata sabai bhanda important learning ke gain garnu bhayo?
