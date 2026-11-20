# MIT No Attribution
#
# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# SPDX-License-Identifier: MIT-0
"""Applicant bands: the ranges band-index keys on. The same boundaries as the generated
history (history_generator.py), so a live decision joins its past peers in one Query.
HUD's limits are "at most" values, so ratio bands include their upper bound
(dti:43-47 means 43 < DTI <= 47); credit-score bands are whole-number ranges."""
CREDIT_BANDS = [(500, 579), (580, 619), (620, 679), (680, 739), (740, 850)]
DTI_BANDS = [(0, 43), (43, 47), (47, 50), (50, 100)]
LTV_BANDS = [(0, 80), (80, 90), (90, 96.5), (96.5, 200)]


def band(value, bands, prefix, whole_numbers=False):
    for lo, hi in bands:
        inside = (lo <= value <= hi) if whole_numbers else (lo < value <= hi or (lo == 0 and value == 0))
        if inside:
            return f"{prefix}:{lo}-{hi}"
    return f"{prefix}:{bands[-1][0]}-{bands[-1][1]}"


def bands_for(credit_score, back_end_dti_pct, ltv_pct):
    """{credit_band, dti_band, ltv_band} for the values a decision read; None if any is missing."""
    if None in (credit_score, back_end_dti_pct, ltv_pct):
        return None
    return {"credit_band": band(float(credit_score), CREDIT_BANDS, "credit", whole_numbers=True),
            "dti_band": band(float(back_end_dti_pct), DTI_BANDS, "dti"),
            "ltv_band": band(float(ltv_pct), LTV_BANDS, "ltv")}
