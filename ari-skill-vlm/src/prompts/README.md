# Visual review prompts

The figure and table templates are bound to a versioned criterion profile.
Responses must satisfy the closed structured-output schema; malformed output is
stored as a raw artifact and returned with `status=schema-error`, never repaired
or converted to an empty success.
