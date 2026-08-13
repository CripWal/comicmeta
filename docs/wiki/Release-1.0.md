# 1.0 Release Checklist

comicmeta is ready for a 1.0 release when the complete user journey works on a
clean macOS installation and against both a local/external library and a NAS
context.

## User-flow checks

- [ ] Install from the documented Homebrew or Python path.
- [ ] First launch explains optional `timg` setup clearly.
- [ ] Dashboard title and controls follow the selected theme.
- [ ] `c`, `s`, `h`, and `q` work from the dashboard.
- [ ] Health displays its result without trapping the user on a blank screen.
- [ ] Organize displays a dry run and applies only after explicit confirmation.
- [ ] Browse opens series and issues, toggles flags, opens gallery, and returns cleanly.
- [ ] Alternate-cover selection only offers named cover candidates.
- [ ] Settings preserves selection and keeps advanced controls discoverable.

## Storage and safety checks

- [ ] Local paths work regardless of the launch directory.
- [ ] Mounted `/Volumes/...` paths work.
- [ ] NAS contexts use their configured remote library path from any launch directory.
- [ ] Appearance is global while library review state remains library-scoped.
- [ ] Health detects corrupt and incomplete archives without mutation.
- [ ] Organize avoids silent guesses and destination collisions.
- [ ] Write creates backups and refuses unsafe archive mutations.

## Quality gate

- [ ] Full automated tests pass.
- [ ] GitHub Actions CI passes on Python 3.11 through 3.14.
- [ ] A clean-machine smoke test passes.
- [ ] A representative local library is opened in the target reader.
- [ ] A representative NAS library is opened in the target reader.
- [ ] README and wiki examples contain no private hostnames, usernames, or paths.
