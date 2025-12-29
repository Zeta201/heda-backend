pr_finalize_template = """\
                            
name: Main Finalize

on:
  push:
    branches: [ main ]

jobs:
  finalize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # Needed to push tags

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

      - name: Upload verification artifacts
        uses: actions/upload-artifact@v4
        with:
          name: verification
          path: verification.json
"""