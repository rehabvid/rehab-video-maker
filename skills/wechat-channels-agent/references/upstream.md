# Upstream

Adapted from:

- https://github.com/wangzhaobo168/wechat-channels-upload
- MIT License, Copyright (c) 2026 wangzhaobo

The upstream project documents the Channels creator UI flow: persistent
Playwright profile, QR login, video upload, short title, description/hashtags,
cover upload, original declaration and publish. This adaptation:

- uses the repo's Playwright installation from `modules/linkZagShow/node_modules`
- runs on macOS and resolves the profile under the user's config directory
- defaults to draft mode and disables original declaration
- validates linkZag manifest fields before launching a browser
- records screenshots/receipts under `build/marketing/wechat/linkZag`
- does not request or store passwords/QR sessions

The selectors are inherently brittle. Treat failures as expected maintenance,
not as a reason to retry in a tight loop.
