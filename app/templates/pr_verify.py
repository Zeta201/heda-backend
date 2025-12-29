pr_verify_template = """\
name: PR Verify

on:
  pull_request:
    branches: [ main ]
    
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install HEDA
        run: |
          pip install --upgrade pip
          pip install git+https://github.com/Zeta201/heda.git
      - name: Finalize experiment
        run: |
          heda finalize
      - name: Verify experiment
        run: |
          heda verify
""" 