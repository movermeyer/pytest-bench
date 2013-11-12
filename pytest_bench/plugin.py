# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals, division
import os
import six
import inspect
# from timeit import timeit
from timeit import default_timer as timer
from functools import wraps
from termcolor import colored
import colorama


def pytest_addoption(parser):
    group = parser.getgroup("general")
    group.addoption('--bench', action='store_true',
                    help="Perform benchmarks on marked test cases.")


def pytest_configure(config):
    if config.option.bench:
        config.pluginmanager.register(BenchmarkController(config), '_bench')


class Benchmark(object):

    def __init__(self, item, elapsed, iterations):
        #! The collected item from pytest.
        self.item = item

        #! The number of elapsed seconds.
        self._elapsed = elapsed

        #! The number of iterations.
        self.iterations = iterations

    @property
    def name(self):
        filename = os.path.relpath(self.item.module.__file__) + ':'
        return '{} {}.{}'.format(
            colored(filename, 'white', attrs=['dark']),
            self.item.cls.__name__,
            self.item.function.__name__)

    @property
    def elapsed(self):
        if self._elapsed and self.iterations:
            return self._elapsed / self.iterations


class BenchmarkController(object):

    def __init__(self, config):
        self.config = config
        self._benchmarks = []
        self._item_function = None

    def pytest_runtest_setup(self, item):

        # Check to see if we need to benchmark any invocations.
        bench = item.keywords.get('bench')
        if bench is None:
            # Nope; nothing to see here.
            return

        # Get the first argument to indicate what method to benchmark.
        expression = bench.args[0]
        iterations = bench.kwargs.get('iterations', 100)

        # Create a wrapper for the test case that applies the benchmark.
        item_function = self._item_function = item.function
        item_function_globals = six.get_function_globals(item_function)
        item_function_argspec = inspect.getargspec(item.function)
        @wraps(item.function)
        def item_function_wrapper(*args, **kwargs):
            # Extract the function from the expression.
            locals_, globals_ = locals(), item_function_globals
            locals_.update(dict(zip(item_function_argspec.args, args)))
            locals_.update(kwargs)
            six.exec_('_function = %s' % expression, globals_, locals_)
            _function = locals_['_function']

            # Initialize benchmark process.
            elapsed = 0.00
            real_iterations = 0

            # Create a wrapper for the method to benchmark.
            @wraps(_function)
            def benchmark(*args, **kwargs):
                nonlocal elapsed, real_iterations
                start = timer()
                result = _function(*args, **kwargs)
                elapsed += timer() - start
                real_iterations += 1
                return result

            # Replace the function with the wrapped function.
            locals_['benchmark'] = benchmark
            six.exec_('%s = benchmark' % expression, globals_, locals_)

            # Attempt to replace it in global scope as well.
            # globals_.update(locals_)

            # Get the (unbound) function.
            try:
                locals_['function'] = six.get_method_function(item_function)

            except AttributeError:
                locals_['function'] = item_function

            # Iterate the set number of iterations.
            item.teardown()
            for _ in range(iterations):
                item.setup()
                locals_['args'] = args
                locals_['kwargs'] = kwargs
                six.exec_('function(*args, **kwargs)', globals_, locals_)
                item.teardown()

            # Restore the benchmarked function.
            six.exec_('%s = _function' % expression, globals_, locals_)

            # Construct a Benchmark instance to store the result.
            self._benchmarks.append(Benchmark(item, elapsed, real_iterations))

        setattr(item.cls, item.function.__name__, item_function_wrapper)

    def pytest_runtest_teardown(self, item):

        # Check to see if we need to handle a benchmark.
        bench = item.keywords.get('bench')
        if bench is None:
            # Nope; nothing to see here.
            return

        if self._item_function is not None:
            # Restore the original item function.
            setattr(item.cls, item.function.__name__, self._item_function)

    def pytest_terminal_summary(self, terminalreporter):
        tr = terminalreporter

        # Ensure terminal output is colored.
        colorama.init()

        # Write session header.
        tr.write_sep('-', 'benchmark session starts')
        tr.write_line('collected %s items' % len(self._benchmarks))
        tr.write('\n')

        # Format and write table header.
        header = '{:<100}{:>15}'.format('Benchmark', 'Time (μs)')
        tr.write_line('-' * 115)
        tr.write_line(header)
        tr.write_line('-' * 115)

        # Iterate through collected benchmarks.
        for benchmark in list(self._benchmarks):
            # Get and truncate the name.
            name = benchmark.name
            name = name[:92] + (name[92:] and '..')

            # Write out the name.
            tr.write('{:<98}'.format(name))

            # Perform the benchmark.
            elapsed = benchmark.elapsed

            if elapsed is None:
                # Write dashes.
                tr.write_line(colored(
                    '{:>30}'.format('----'), 'white', attrs=['dark']))

            else:
                # Convert to microseconds.
                elapsed *= 10 ** 6

                # Write out the elapsed.
                tr.write_line(colored(
                    '{:>30,.4f}'.format(elapsed), 'white', attrs=['bold']))