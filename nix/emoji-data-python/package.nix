# nixpkgs-style package for emoji-data-python.
# Drop-in for pkgs/development/python-modules/emoji-data-python/package.nix
# (add `emoji-data-python = callPackage ../development/python-modules/emoji-data-python { };`
# to pkgs/top-level/python-packages.nix when upstreaming).
{
  lib,
  buildPythonPackage,
  fetchPypi,
  setuptools,
  unittestCheckHook,
}:

buildPythonPackage rec {
  pname = "emoji-data-python";
  version = "1.6.0";
  pyproject = true;

  src = fetchPypi {
    pname = "emoji_data_python"; # sdist uses the underscored name
    inherit version;
    hash = "sha256-a+ZzjzaMgnZI2pP77fCBFsPTF9M4pVQJ9059dZ+g41Q=";
  };

  build-system = [ setuptools ];

  # no runtime dependencies (the emoji dataset is bundled)

  nativeCheckInputs = [ unittestCheckHook ];

  pythonImportsCheck = [ "emoji_data_python" ];

  meta = {
    description = "Python emoji toolkit built on the iamcal emoji-data set";
    homepage = "https://github.com/alexmick/emoji-data-python";
    license = lib.licenses.mit;
    maintainers = [ ]; # add your nixpkgs maintainer handle when upstreaming
  };
}
