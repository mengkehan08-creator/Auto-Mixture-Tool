"""Copy OUTSIDE the repository, then fill credentials on the development server.

Set AMT_IAM_PROVIDER to the absolute path of that private copy and restart UI.
This tracked template must contain placeholders only. Never upload the private
copy to GitHub or OBS. Authorization is used by the backend, not sent to the UI.
"""

AUTH_CONFIG = {
    'account': 'REPLACE_ME_ACCOUNT',
    'secret': 'REPLACE_ME_SECRET',
    'project': 'REPLACE_ME_PROJECT',
    'enterprise': 'REPLACE_ME_ENTERPRISE',
    # Optional independent job URL allowlist. Empty uses the trusted CSB gateway
    # and account scope; the legacy auth['endpoint'] is never used here.
    'modelarts_endpoint': '',
    # Empty = raw access_token; set to 'Bearer ' only if required by your gateway.
    'authorization_prefix': '',
    # Optional absolute path to your organization's trusted CA certificate.
    'ca_bundle': '',
    # IAM only: False disables server identity verification (credential risk).
    'iam_verify_ssl': True,
}
