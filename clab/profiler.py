from __future__ import absolute_import, division, print_function, unicode_literals
from six.moves import range, cStringIO
import six
import operator
import sys
import ubelt as ub

if '--profile' in sys.argv:
    import line_profiler
    profile = line_profiler.LineProfiler()
    IS_PROFILING = True
else:
    def __dummy_profile__(func):
        """ dummy profiling func. does nothing """
        return func
    profile = __dummy_profile__
    IS_PROFILING = False


def dynamic_profile(func):
    import line_profiler
    profile = line_profiler.LineProfiler()
    new_func = profile(func)
    new_func.profile_info = KernprofParser(profile)
    new_func.print_report = new_func.profile_info.print_report
    return new_func


def profile_onthefly(func):
    import line_profiler
    profile = line_profiler.LineProfiler()
    new_func = profile(func)
    new_func.profile_info = KernprofParser(profile)
    new_func.print_report = new_func.profile_info.print_report

    def wraper(*args, **kwargs):
        retval = new_func(*args, **kwargs)
        new_func.print_report()
        return retval

    return wraper


class KernprofParser(object):

    def __init__(self, profile):
        self.profile = profile

    def raw_text(self):
        file_ = cStringIO()
        self.profile.print_stats(stream=file_, stripzeros=True)
        file_.seek(0)
        text =  file_.read()
        return text

    def print_report(self):
        print(self.raw_text())

    def get_text(self):
        text = self.raw_text()
        output_text, summary_text = self.clean_line_profile_text(text)
        return output_text, summary_text

    def dump_text(self):
        print("Dumping Profile Information")
        try:
            output_text, summary_text = self.get_text()
        except AttributeError:
            print('profile is not on')
        else:
            #profile.dump_stats('out.lprof')
            import ubelt as ub
            print(summary_text)
            ub.writeto('profile_output.txt', output_text + '\n' + summary_text)
            ub.writeto('profile_output.%s.txt' % (ub.timestamp()),
                       output_text + '\n' + summary_text)

    def parse_rawprofile_blocks(self, text):
        """
        Split the file into blocks along delimters and and put delimeters back in
        the list
        """
        # The total time reported in the raw output is from pystone not kernprof
        # The pystone total time is actually the average time spent in the function
        delim = 'Total time: '
        delim2 = 'Pystone time: '
        import re
        #delim = 'File: '
        profile_block_list = re.split('^' + delim, text, flags=re.MULTILINE | re.DOTALL)
        for ix in range(1, len(profile_block_list)):
            profile_block_list[ix] = delim2 + profile_block_list[ix]
        return profile_block_list

    def clean_line_profile_text(self, text):
        """
        Sorts the output from line profile by execution time
        Removes entries which were not run
        """
        #
        profile_block_list = self.parse_rawprofile_blocks(text)
        #profile_block_list = fix_rawprofile_blocks(profile_block_list)
        #---
        # FIXME can be written much nicer
        prefix_list, timemap = self.parse_timemap_from_blocks(profile_block_list)
        # Sort the blocks by time
        sorted_lists = sorted(six.iteritems(timemap), key=operator.itemgetter(0))
        newlist = prefix_list[:]
        for key, val in sorted_lists:
            newlist.extend(val)
        # Rejoin output text
        output_text = '\n'.join(newlist)
        #---
        # Hack in a profile summary
        summary_text = self.get_summary(profile_block_list)
        output_text = output_text
        return output_text, summary_text

    def get_block_totaltime(self, block):

        def get_match_text(match):
            if match is not None:
                start, stop = match.start(), match.end()
                return match.string[start:stop]
            else:
                return None

        import re
        time_line = get_match_text(re.search('Pystone time: [0-9.]* s', block, flags=re.MULTILINE | re.DOTALL))
        time_str = get_match_text(re.search('[0-9.]+', time_line, flags=re.MULTILINE | re.DOTALL))
        if time_str is not None:
            return float(time_str)
        else:
            return None

    def get_block_id(self, block):

        def named_field(key, regex, vim=False):
            return r'(?P<%s>%s)' % (key, regex)

        import re
        fpath_regex = named_field('fpath', '\S+')
        funcname_regex = named_field('funcname', '\S+')
        lineno_regex = named_field('lineno', '[0-9]+')

        fileline_regex = 'File: ' + fpath_regex + '$'
        funcline_regex = 'Function: ' + funcname_regex + ' at line ' + lineno_regex + '$'
        fileline_match = re.search(fileline_regex, block, flags=re.MULTILINE)
        funcline_match = re.search(funcline_regex, block, flags=re.MULTILINE)
        if fileline_match is not None and funcline_match is not None:
            fpath    = fileline_match.groupdict()['fpath']
            funcname = funcline_match.groupdict()['funcname']
            lineno   = funcline_match.groupdict()['lineno']
            block_id = funcname + ':' + fpath + ':' + lineno
        else:
            block_id = 'None:None:None'
        return block_id

    def parse_timemap_from_blocks(self, profile_block_list):
        """
        Build a map from times to line_profile blocks
        """
        prefix_list = []
        timemap = ub.ddict(list)
        for ix in range(len(profile_block_list)):
            block = profile_block_list[ix]
            total_time = self.get_block_totaltime(block)
            # Blocks without time go at the front of sorted output
            if total_time is None:
                prefix_list.append(block)
            # Blocks that are not run are not appended to output
            elif total_time != 0:
                timemap[total_time].append(block)
        return prefix_list, timemap

    def get_summary(self, profile_block_list, maxlines=20):
        """
        References:
            https://github.com/rkern/line_profiler
        """
        time_list = [self.get_block_totaltime(block) for block in profile_block_list]
        time_list = [time if time is not None else -1 for time in time_list]
        blockid_list = [self.get_block_id(block) for block in profile_block_list]
        sortx = ub.argsort(time_list)
        sorted_time_list = list(ub.take(time_list, sortx))
        sorted_blockid_list = list(ub.take(blockid_list, sortx))

        import utool as ut
        aligned_blockid_list = ut.util_str.align_lines(sorted_blockid_list, ':')
        summary_lines = [('%6.2f seconds - ' % time) + line
                         for time, line in
                         zip(sorted_time_list, aligned_blockid_list)]
        #summary_header = ut.codeblock(
        #    '''
        #    CLEANED PROFILE OUPUT

        #    The Pystone timings are not from kernprof, so they may include kernprof
        #    overhead, whereas kernprof timings do not (unless the line being
        #    profiled is also decorated with kernrof)

        #    The kernprof times are reported in Timer Units

        #    ''')
        # summary_lines_ = ut.listclip(summary_lines, maxlines, fromback=True)
        summary_text = '\n'.join(summary_lines[-maxlines:])
        return summary_text

    def fix_rawprofile_blocks(self, profile_block_list):
        # TODO: finish function. should multiply times by
        # Timer unit to get true second profiling
        #profile_block_list_new = []
        for block in profile_block_list:
            block_lines = block.split('\n')
            sep = ['=' * 62]
            def split_block_at_sep(block_lines, sep):
                for pos, line in enumerate(block_lines):
                    if line.find(sep) == 0:
                        pos += 1
                        header_lines = block_lines[:pos]
                        body_lines = block_lines[pos:]
                        return header_lines, body_lines
                return block_lines, None
            header_lines, body_lines = split_block_at_sep(block_lines, sep)

    def clean_lprof_file(self, input_fname, output_fname=None):
        """ Reads a .lprof file and cleans it """
        # Read the raw .lprof text dump
        text = ub.readfrom(input_fname)
        # Sort and clean the text
        output_text = self.clean_line_profile_text(text)
        return output_text
