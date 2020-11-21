This is forked a pylint checker for russian language to check for strings in python source code that has not been passed through gettext/_.

For more information see the homepage: http://www.technomancy.org/python/pylint-i18n-lint-checker/

Example:

* `pylint -E --load-plugins missing_gettext --disable=all --enable=non-gettext-string project/`
