import re

from astroid.node_classes import *
from pylint.checkers import BaseChecker
from pylint.interfaces import IAstroidChecker

# django model field cls names
from django.db.models import __all__


def is_number(text):
    """Returns True if this text is a representation of a number"""
    try:
        float(text)
        return True
    except ValueError:
        return False


def is_child_node(child, parent):
    """Returns True if child is an eventual child node of parent"""
    node = child
    while node is not None:
        if node == parent:
            return True
        node = node.parent
    return False


def _is_cyrillic_str(obj):
    """String is cyrillic"""
    return isinstance(obj, str) and bool(re.search('[а-яА-Я]', obj))


def _is_regex(obj):
    """String is probably regex"""
    return (
        (
                obj.startswith('^')
                and obj.endswith('$')
                or any(i in obj for i in ['[^', 'а-я', 'А-Я'])
        ),
    )


def _is_comment_in_sql(obj: str):
    """"""
    rows = obj.split('\n')
    rows = [i.strip() for i in rows]
    return any(i.startswith('--') for i in rows)


class MissingGettextRuChecker(BaseChecker):
    """Checks for strings that aren't wrapped in a _ call somewhere."""

    __implements__ = IAstroidChecker

    name = 'missing_gettext'
    msgs = {
        'W0001': (
            'non-gettext-ed string %r',
            'non-gettext-string',
            "There is a raw string that's not passed through gettext",
        ),
    }

    # this is important so that your checker is executed before others
    priority = -1

    def visit_const(self, node):
        if not _is_cyrillic_str(node.value):
            return

        # Ignore some strings based on the contents.
        # Each element of this list is a one argument function. if any of them
        # return true for this string, then this string is ignored
        whitelisted_strings = [
            # ignore empty strings
            lambda x: x == '',
            is_number,
            # probably a regular expression
            lambda x: x.startswith('^') and x.endswith('$'),
            lambda x: '[^' in x or 'а-я' in x or 'А-Я' in x,
            # probably URL or path fragment
            lambda x: x.startswith('/') or x.endswith('/'),
            _is_comment_in_sql,
        ]

        for func in whitelisted_strings:
            if func(node.value):
                return

        # Whitelist some strings based on the structure.
        # Each element of this list is a 2-tuple, class and then a 2 arg
        # function. Starting with the current string, and going up the parse
        # tree to the root (i.e. the whole file), for every whitelist element,
        # if the current node is an instance of the first element, then the
        # 2nd element is called with that node and the original string. If
        # that returns True, then this string is assumed to be OK.
        # If any parent node of this string returns True for any of these
        # functions then the string is assumed to be OK
        whitelist = [
            # {'shouldignore': 1}
            (Dict, lambda curr_node, node: node in [x[0] for x in curr_node.items]),
            # dict['shouldignore']
            (Index, lambda curr_node, node: curr_node.value == node),
            # class Meta:
            #     db_table = 'Заказ'
            (
                Assign,
                lambda curr_node, node: (
                        len(curr_node.targets) == 1
                        and hasattr(curr_node.targets[0], 'name')
                        and curr_node.targets[0].name
                        in ['db_table', 'verbose_name', 'verbose_name_plural',]
                ),
            ),
            # Just a random doc-string-esque string in the code
            (Delete, lambda curr_node, node: curr_node.value == node),
            # x = CharField(verbose_name='xxx', help_text='xxx')
            (
                Keyword,
                lambda curr_node, node: (
                        curr_node.arg in ['verbose_name', 'help_text',]
                        and curr_node.value == node
                ),
            ),
            # something() == 'string'
            (Compare, lambda curr_node, node: node == curr_node.ops[0][1]),
            # 'something' == blah()
            (Compare, lambda curr_node, node: node == curr_node.left),
            # Queryset functions, queryset.order_by('shouldignore')
            (
                Call,
                lambda curr_node, node: (
                        isinstance(curr_node.func, Attribute)
                        and curr_node.func.attrname
                        in [
                            'has_key',
                            'pop',
                            'order_by',
                            'strftime',
                            'strptime',
                            'get',
                            'select_related',
                            'values',
                            'filter',
                            'values_list',
                        ]
                ),
            ),
            # logging.info('shouldignore')
            (
                Call,
                lambda curr_node, node: curr_node.func.expr.name
                                        in ['logging', 'logger', 'console_logger'],
            ),
            # models arg is verbose_name if it is first
            # x = models.CharField('Дата создания', default='')
            (
                Call,
                lambda curr_node, node: (
                        curr_node.func.attrname in __all__
                        and hasattr(curr_node, 'args')
                        and isinstance(curr_node.args, list)
                        and len(curr_node.args) > 0
                        and curr_node.args[0] == node
                ),
            ),
        ]

        string_ok = False
        debug = False
        curr_node = node

        # we have a string. Go upwards to see if we have a _ function call
        try:
            while curr_node.parent is not None:
                if debug:
                    print(repr(curr_node))
                    print(repr(curr_node.as_string()))
                    print(curr_node.repr_tree())
                if isinstance(curr_node, Call):
                    if hasattr(curr_node, 'func') and hasattr(curr_node.func, 'name'):
                        if curr_node.func.name in [
                            '_',
                            'ugettext',
                            'ugettext_lazy',
                            'gettext',
                            'gettext_lazy',
                            'pgettext',
                            'pgettext_lazy',
                            'ngettext',
                            'ngettext_lazy',
                        ]:
                            # we're in a _() call
                            string_ok = True
                            break

                # Look at our whitelist
                for cls, func in whitelist:
                    if isinstance(curr_node, cls):
                        try:
                            # Ignore any errors from here. Otherwise we have to
                            # pepper the whitelist with loads of defensive
                            # hasattrs, which increase bloat
                            if func(curr_node, node):
                                string_ok = True
                                break
                        except AttributeError:
                            pass

                curr_node = curr_node.parent

        except Exception as error:
            print(node, node.as_string())
            print(curr_node, curr_node.as_string())
            print(error)

        if not string_ok:
            # we've gotten to the top of the code tree / file level and we
            # haven't been whitelisted, so add an error here
            self.add_message('W0001', node=node, args=node.value)


def load_configuration(linter):
    """Amend existing checker config."""
    linter.config.black_list += ('migrations', 'tests', 'factories.py', 'tests.py')


def register(linter):
    """Required method to auto register this checker"""
    linter.register_checker(MissingGettextRuChecker(linter))
