# reporting/__init__.py
"""Platform report writers and vulnerability taxonomy (S3.2).

Fed ONLY by CONFIRMED / CHAINED findings from the triage state machine —
no report is generated for an unconfirmed finding (ReportGateError).
"""
