{
  description = "slak — a terminal Slack client built on Textual";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
        py = python.pkgs;
        pyproject = builtins.fromTOML (builtins.readFile ./pyproject.toml);

        # emoji-data-python isn't in nixpkgs yet — built from a nixpkgs-style
        # expression (see ./nix/emoji-data-python) that's ready to upstream as-is.
        emoji-data-python = py.callPackage ./nix/emoji-data-python/package.nix { };

        # Runtime dependencies (all the others are in nixpkgs).
        runtimeDeps = [
          py.textual
          py.httpx
          py.websockets
          py.tomlkit
          py.wcwidth
          py.pillow
          emoji-data-python
        ];

        slak = py.buildPythonApplication {
          pname = "slak";
          version = pyproject.project.version; # read from pyproject.toml — no drift
          pyproject = true;
          src = ./.;
          build-system = [ py.setuptools ];
          dependencies = runtimeDeps;
          # The test suite drives a Textual Pilot (needs a pty) — run it with
          # `nix develop` + pytest, not in the build sandbox.
          doCheck = false;
          pythonImportsCheck = [ "slak" ];
          meta = with pkgs.lib; {
            description = "A terminal Slack client built on Textual";
            homepage = "https://github.com/Frodotus/slak";
            license = licenses.gpl3Plus;
            mainProgram = "slak";
          };
        };
      in {
        packages.default = slak;
        packages.slak = slak;

        apps.default = {
          type = "app";
          program = "${slak}/bin/slak";
        };

        devShells.default = pkgs.mkShell {
          packages = [
            (python.withPackages (ps:
              runtimeDeps ++ [
                ps.pytest
                ps.pytest-asyncio
              ]))
          ];
          # Put the working tree on the path so `import slak` / `python -m slak`
          # and the test suite run against your checkout (no install step needed).
          shellHook = ''
            export PYTHONPATH="$PWD''${PYTHONPATH:+:$PYTHONPATH}"
            echo "slak dev shell — run: pytest -q   |   python -m slak"
          '';
        };
      });
}
