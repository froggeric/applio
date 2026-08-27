# PR 8 — branch `upstream-pr/i18n-strings` (commit 2aadfbe5) — DRAFT, NOT SUBMITTED

## Title

Accessibility improvements: translate the remaining user facing strings and show real language names in the picker

## Body

A pass over the app found about forty strings the user sees but the translation system never touches:
- the prerequisites check messages on the training tab
- model path errors
- several info and warning toasts
- the plugin install messages
- and a number of smaller ones
All of them are now wrapped in i18n() like the rest of the UI, and the English keys are in en_US.json

The language picker used to show raw codes like "fr_FR" and "pt_BR". It now shows each language in its own spelling, for example "Français (fr_FR)" or "日本語 (ja_JP)", built at runtime from the files that are actually installed. It behaves nicely when locales are added (a locale without a name entry simply shows its code). The stored setting is still the raw code; nothing about how the choice is saved changes.

Verified on macos with voiceover in english, spanish, and french.

(this is probably the last accessibility PR... for now :-D I have got nothing else planned along that line, but you never know what might come up)