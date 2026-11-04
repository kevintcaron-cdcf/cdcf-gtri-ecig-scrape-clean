Updates - Nov 11, 2025
----------------------

Agenda
======

- Updates

  - CV
  - Reviews Initial Analysis
  - Price Analysis
  - NLP
  - Publication


Iced Vape Juice Update
======================

- Since our last meeting we have continued to run our VLM pipeline for iced vape juice detection.

- We have now manually validated over 2000 products and found the model is over 99% accurate in detecting iced juice flavors.

- I believe we have validated enough of these products to prove that this pipeline is well suited for this problem.

- With these results, I think we should move on to repeating this experiment with disposable vapes.

- The combination of these two experiments should make for a compelling paper.



Performance Matrix
==================

+-------------------+-----------+-----------+-------------+-----------+
| Site              | # Verified| # Correct | # Incorrect | Accuracy  |
+===================+===========+===========+=============+===========+
| vape.com          | 613       | 606       | 7           | 98.86%    |
+-------------------+-----------+-----------+-------------+-----------+
| elementvape.com   | 898       | 892       | 6           | 99.33%    |
+-------------------+-----------+-----------+-------------+-----------+
| vapingdotcom      | 232       | 230       | 2           | 99.14%    |
+-------------------+-----------+-----------+-------------+-----------+
| vapewh.com        | 58        | 58        | 0           | 100.00%   |
+-------------------+-----------+-----------+-------------+-----------+
| getpop.com        | 56        | 56        | 0           | 100.00%   |
+-------------------+-----------+-----------+-------------+-----------+
| csvape.com        | 326       | 325       | 1           | 99.69%    |
+-------------------+-----------+-----------+-------------+-----------+
| **TOTAL**         | **2183**  | **2167**  | **16**      | **99.27%**|
+-------------------+-----------+-----------+-------------+-----------+

Error Analysis of 16 Incorrect Predictions
==========================================

- 2 – “Cool Aloe Vera” in product description, model incorrectly marked as cooling
- 4 – Mint and Spearmint flavors incorrectly marked as not cooling
- 2 – Model missed reviews which indicated cooling
- 1 – Model quoted language of cool menthol not present in product description
- 1 – Model read “ice” in “ice cream” and incorrectly marked as cooling
- 2 – Model read “iced” in “iced tea” and incorrectly marked as cooling
- 1 – Model read “shiver the faculties” and incorrectly marked as cooling
- 1 – Model read “snow cone” and incorrectly marked as cooling
- 1 – Model read “cool crisp apple” and incorrectly marked as cooling
- 1 – Model read “cool smooth milk on exhale” and incorrectly marked as cooling

Current Prompt and Performance
==============================

Text Prompt
-----------

You are a public health bot to a customer review whether reviews for the e-cigarette product is menthol-based. Certain indicators include words like 'iced', 'menthol', 'icy', 'cooling', 'newport-like', 'cool sensation' etc.

'Mint' flavors may be iced, but only label as 'iced' if there is an indication beyond just mint, such as menthol.

Return the result as value JSON (with valid quote) in the following format:


    {
      "result": true,
      "justification": "This product is iced because the user mentions a cooling sensation."
    }

Here is the review:

# Comparing 500 labels

# Precision: 0.94
# Recall: 0.79
# F1 Score: 0.86
# Accuracy: 0.98

