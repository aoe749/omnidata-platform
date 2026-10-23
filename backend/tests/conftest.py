import os

# Settings require secrets; supply throwaway values before the app is imported.
for key, value in {
    "JWT_SECRET": "test-secret-test-secret-test-secret-0123",
    "DEMO_PASSWORD": "test-demo-password-123",
    "MSSQL_PASSWORD": "unused-in-unit-tests",
    "POSTGRES_PASSWORD": "unused-in-unit-tests",
    "MYSQL_PASSWORD": "unused-in-unit-tests",
}.items():
    os.environ.setdefault(key, value)
