# Aurora Image Build System Architecture

This document explains how the Aurora desktop image is built from multiple "common" repositories, how files flow between them, and how build variants work.

## Repository Roles

| Repo | Published Image | Role |
|------|----------------|------|
| **bluefin-common** | `ghcr.io/projectbluefin/common` | Shared config for Bluefin (GNOME) and Aurora (KDE). Provides `system_files/shared/` (cross-desktop), `system_files/bluefin/` (GNOME-only), and `system_files/nvidia/` |
| **aurora-common** | `ghcr.io/get-aurora-dev/common` | Aurora/KDE-specific config. Provides `system_files/shared/`, `system_files/dx/`, wallpapers, logos, just recipes, flatpak lists, and brew definitions |
| **aurora** | `ghcr.io/ublue-os/aurora` (+ variants) | Final image build. Uses `Containerfile.in` with C preprocessor conditionals for NVIDIA/ZFS variants |
| **brew** | `ghcr.io/ublue-os/brew` | Homebrew integration layer. Contributes system files (Brewfiles, brew-setup service) |

## 1. OCI Image Composition Chain

This diagram shows how each published OCI image feeds into the next, ending at the final Aurora image. The `ctx` stage assembles all file sources before they are copied into the running image.

```mermaid
flowchart TD
    subgraph "External Base Images"
        KINOITE["quay.io/fedora-ostree-desktops/kinoite:43<br/><i>Fedora Kinoite base</i>"]
        AKMODS["ghcr.io/ublue-os/akmods<br/><i>Kernel modules</i>"]
        AKMODS_NVIDIA["ghcr.io/ublue-os/akmods-nvidia-open<br/><i>NVIDIA kernel modules</i>"]
        AKMODS_ZFS["ghcr.io/ublue-os/akmods-zfs<br/><i>ZFS kernel modules</i>"]
    end

    subgraph "Common Layer Images (FROM scratch)"
        BLUEFIN_COMMON["ghcr.io/projectbluefin/common<br/><i>bluefin-common repo</i>"]
        AURORA_COMMON["ghcr.io/get-aurora-dev/common<br/><i>aurora-common repo</i>"]
        BREW["ghcr.io/ublue-os/brew<br/><i>brew repo</i>"]
    end

    subgraph "aurora repo: ctx stage (FROM scratch)"
        CTX["ctx stage<br/>Assembles all files under /system_files/ and /build_files/"]
    end

    subgraph "aurora repo: base stage"
        BASE["Final Aurora Image<br/><i>FROM kinoite:43</i>"]
    end

    AURORA_COMMON -->|"COPY --from=common /logos → /system_files/shared<br/>COPY --from=common /system_files → /system_files<br/>COPY --from=common /wallpapers → /system_files/shared"| CTX
    BREW -->|"COPY --from=brew /system_files → /system_files/shared"| CTX
    BLUEFIN_COMMON -.->|"Referenced inside aurora-common's Containerfile:<br/>COPY --from=projectbluefin/common /system_files/nvidia → /system_files/nvidia"| AURORA_COMMON

    CTX -->|"--mount=type=bind,from=ctx → /ctx<br/>build.sh runs: rsync /ctx/system_files/shared/ /"| BASE
    KINOITE -->|"FROM base image"| BASE
    AKMODS -->|"--mount kernel-rpms, rpms/common, rpms/kmods"| BASE
    AKMODS_NVIDIA -->|"--mount rpms (NVIDIA only)"| BASE
    AKMODS_ZFS -->|"--mount rpms/kmods/zfs (ZFS only)"| BASE

    style CTX fill:#2d5016,stroke:#4a8529,color:#fff
    style BASE fill:#1a3a5c,stroke:#2d6da3,color:#fff
    style BLUEFIN_COMMON fill:#5c3a1a,stroke:#a36d2d,color:#fff
    style AURORA_COMMON fill:#5c3a1a,stroke:#a36d2d,color:#fff
    style BREW fill:#5c3a1a,stroke:#a36d2d,color:#fff
```

### Key details

- **bluefin-common** and **aurora-common** both publish `FROM scratch` images containing only configuration files -- no OS, no runtime. They are pure data layers.
- **aurora-common** itself pulls from **bluefin-common** during its own build: `COPY --from=ghcr.io/projectbluefin/common:latest /system_files/nvidia /system_files/nvidia`
- The aurora repo's **ctx stage** assembles all sources, then the **base stage** bind-mounts ctx at `/ctx` and uses `rsync` to copy files into the live Fedora Kinoite filesystem.
- **akmods** images are never copied into ctx -- they are bind-mounted directly into the base stage's RUN commands as `/tmp/kernel-rpms`, `/tmp/rpms/common`, `/tmp/rpms/kmods`, etc.

## 2. system_files Directory Merge Order

Files are layered in a specific order. **Later copies overwrite earlier ones**, so aurora's own `system_files/` has the final say.

```mermaid
flowchart TD
    subgraph "ctx stage assembly (Containerfile.in lines 25-37)"
        direction TB
        S1["1. COPY --from=common /logos → /system_files/shared<br/><i>Aurora logos from aurora-common</i>"]
        S2["2. COPY --from=common /system_files → /system_files<br/><i>aurora-common's shared/ and dx/ trees</i>"]
        S3["3. COPY --from=common /wallpapers → /system_files/shared<br/><i>Aurora wallpapers</i>"]
        S4["4. COPY --from=brew /system_files → /system_files/shared<br/><i>Brew system files (Brewfiles, services)</i>"]
        S5["5. COPY /system_files → /system_files<br/><i>Aurora repo's own overrides</i>"]

        S1 --> S2 --> S3 --> S4 --> S5
    end

    subgraph "base stage: build.sh applies files"
        direction TB
        R1["rsync /ctx/system_files/shared/ /<br/><i>Merged shared tree → filesystem root</i>"]
        R2["rsync /ctx/system_files/dx/ /<br/><i>(only if IMAGE_FLAVOR=dx)</i>"]

        R1 --> R2
    end

    S5 --> R1

    style S5 fill:#1a3a5c,stroke:#2d6da3,color:#fff
    style R1 fill:#2d5016,stroke:#4a8529,color:#fff
    style R2 fill:#2d5016,stroke:#4a8529,color:#fff
```

### What each layer contributes

| Order | Source | Destination in ctx | Contents |
|-------|--------|-------------------|----------|
| 1 | aurora-common `/logos` | `/system_files/shared` | Aurora SVG logos (distributor-logo, banner, pride variants) |
| 2 | aurora-common `/system_files` | `/system_files` | `shared/` (KDE configs, scripts, systemd units, skel, SDDM theme, polkit, etc.) and `dx/` (VS Code, Docker, Incus configs) |
| 3 | aurora-common `/wallpapers` | `/system_files/shared` | Processed KDE wallpapers under `usr/share/backgrounds/aurora/` and `usr/share/wallpapers/` |
| 4 | brew `/system_files` | `/system_files/shared` | Homebrew Brewfiles, brew-setup systemd service |
| 5 | aurora repo `/system_files` | `/system_files` | Aurora-specific overrides: `rpm-ostreed.conf`, `flatpak-nuke-fedora.service`, SDDM themes mount, COPR vendor config, bazaar preinstall |

### Note on the "shared" name collision

- **bluefin-common** has `system_files/shared/` = files shared across **both** Bluefin (GNOME) and Aurora (KDE) desktops (udev rules, ujust completions, shell configs, container signing keys)
- **aurora-common** has `system_files/shared/` = files specific to **Aurora/KDE** (SDDM theme, KDE Plasma look-and-feel, Ptyxis terminal config, KDE default settings)
- These are different scopes but get merged into the same `/system_files/shared/` directory in the ctx stage. Since aurora-common's files are copied first (step 2) and brew's files overlay next (step 4), then aurora's own files last (step 5), the merge is additive with later files winning on conflict.

## 3. Build Script Execution Order

The `Containerfile.in` uses the C preprocessor to select which variant to build. The Justfile passes flags like `--cpp-flag=-DNVIDIA` and `--cpp-flag=-DZFS` based on the image name and tag.

### How variants are selected (Justfile logic)

```
image name contains "nvidia"  →  -DNVIDIA flag
akmods_flavor = "coreos-stable" (i.e., tag=stable)  →  -DZFS flag
```

### Execution order per variant

```mermaid
flowchart TD
    subgraph "Phase 1: Online (network available)"
        BUILD["build.sh<br/><i>rsync shared/ to /, set up ghcurl helper</i><br/><i>if dx: run build-dx.sh (rsync dx/ to /)</i>"]
        PKG["01-packages.sh<br/><i>Install RPM packages</i>"]
        KERN["02-install-common-kernel-akmods.sh<br/><i>Install kernel + kernel modules</i>"]
        FETCH["03-fetch.sh<br/><i>Fetch network resources</i>"]
        NVIDIA["04-nvidia.sh<br/><i>Install NVIDIA drivers</i>"]
        ZFS["zfs.sh<br/><i>Install ZFS kernel modules</i>"]
    end

    subgraph "Phase 2: Offline (--network=none)"
        OVERRIDE["16-override-install.sh<br/><i>Post-install file overrides</i>"]
        CLEANUP["17-cleanup.sh<br/><i>Enable/disable systemd services, disable repos</i>"]
        IMGINFO["18-image-info.sh<br/><i>Write image metadata</i>"]
        INITRAMFS["19-initramfs.sh<br/><i>Generate initramfs</i>"]
        VALIDATE["validate-repos.sh<br/><i>Validate repo state</i>"]
        CLEAN["clean-stage.sh<br/><i>Remove build artifacts</i>"]
        TESTS["20-tests.sh<br/><i>Run validation tests</i>"]
    end

    subgraph "Phase 3: Final validation"
        LINT["bootc container lint"]
    end

    BUILD --> PKG --> KERN

    KERN -->|"Base"| FETCH
    KERN -->|"ZFS only"| ZFS_BEFORE["zfs.sh"] --> FETCH_ZFS["03-fetch.sh"]
    KERN -->|"NVIDIA only"| FETCH --> NVIDIA
    KERN -->|"NVIDIA+ZFS"| FETCH_BOTH["03-fetch.sh"] --> NVIDIA_BOTH["04-nvidia.sh"] --> ZFS_BOTH["zfs.sh"]

    FETCH --> OVERRIDE
    FETCH_ZFS --> OVERRIDE
    NVIDIA --> OVERRIDE
    ZFS_BOTH --> OVERRIDE

    OVERRIDE --> CLEANUP --> IMGINFO --> INITRAMFS --> VALIDATE --> CLEAN --> TESTS --> LINT
```

### Variant-specific script sequences (exact order)

| Variant | Flags | Online Phase Script Order |
|---------|-------|--------------------------|
| **Base** | _(none)_ | `build.sh` → `01-packages.sh` → `02-install-common-kernel-akmods.sh` → `03-fetch.sh` |
| **ZFS** | `-DZFS` | `build.sh` → `01-packages.sh` → `02-install-common-kernel-akmods.sh` → `zfs.sh` → `03-fetch.sh` |
| **NVIDIA** | `-DNVIDIA` | `build.sh` → `01-packages.sh` → `02-install-common-kernel-akmods.sh` → `03-fetch.sh` → `04-nvidia.sh` |
| **NVIDIA+ZFS** | `-DNVIDIA -DZFS` | `build.sh` → `01-packages.sh` → `02-install-common-kernel-akmods.sh` → `03-fetch.sh` → `04-nvidia.sh` → `zfs.sh` |

All variants then run the same **offline phase**: `16-override-install.sh` → `17-cleanup.sh` → `18-image-info.sh` → `19-initramfs.sh` → `validate-repos.sh` → `clean-stage.sh` → `20-tests.sh`

And the final **lint phase**: `bootc container lint`

### What build.sh does at the start of every build

1. Sets `keepcache=1` for faster rebuilds
2. Swaps `fedora-logos` for `generic-logos` (then erases generic-logos from RPM DB to unblock downstream `-logos` packages)
3. Runs `rsync -rvKl /ctx/system_files/shared/ /` -- this copies the merged shared tree into the filesystem root
4. If `IMAGE_FLAVOR == "dx"`, calls `build-dx.sh` which runs `rsync -rvK /ctx/system_files/dx/ /` and configures Docker/iptables support
5. Installs the `ghcurl` helper script to `PATH`

### What 17-cleanup.sh does in the offline phase

- Enables systemd services: `rpm-ostree-countme`, `tailscaled`, `dconf-update`, `brew-setup`, `aurora-groups`, `usr-share-sddm-themes.mount`, `ublue-system-setup`, `input-remapper`, `flatpak-nuke-fedora`, `flatpak-preinstall`
- Enables user services: `ublue-user-setup`, `podman-auto-update.timer`
- Enables `uupd.timer` (update timer), disables old `rpm-ostreed-automatic.timer`
- Hides desktop entries for `htop` and `nvtop`
- Disables all third-party repos that were added during the build (fedora-multimedia, tailscale, Terra, COPR repos, RPM Fusion, etc.)
