pr_title_template = "Propose experiment {proposal_hash}"

pr_doc_template = """\### Experiment Proposal


- Proposal hash: {proposal_hash}
- Branch: {branch_name}

This PR triggers reproducibility verification.
If merged, the experiment will be versioned automatically.
"""