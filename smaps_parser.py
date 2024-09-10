#!/usr/bin/env python

from optparse import OptionParser
from tempfile import NamedTemporaryFile
import os
import enum
import re


class Heap(enum.Enum):
    HEAP_UNKNOWN = 0, 'Unknown'
    HEAP_DALVIK = 1, 'Dalvik'
    HEAP_NATIVE = 2, 'Native'
    HEAP_DALVIK_OTHER = 3, 'Dalvik Other'
    HEAP_STACK = 4, 'Stack'
    HEAP_CURSOR = 5, 'Cursor'
    HEAP_ASHMEM = 6, 'Ashmem'
    HEAP_GL_DEV = 7, 'Gfx dev'
    HEAP_UNKNOWN_DEV = 8, 'Other dev'
    HEAP_SO = 9, '.so mmap'
    HEAP_JAR = 10, '.jar mmap'
    HEAP_APK = 11, '.apk mmap'
    HEAP_TTF = 12, '.ttf mmap'
    HEAP_DEX = 13, '.dex mmap'
    HEAP_OAT = 14, '.oat mmap'
    HEAP_ART = 15, '.art mmap'
    HEAP_UNKNOWN_MAP = 16, 'Other mmap'
    HEAP_GRAPHICS = 17, 'EGL mtrack'
    HEAP_GL = 18, 'GL mtrack'
    HEAP_OTHER_MEMTRACK = 19, 'Other mtrack'

    HEAP_DALVIK_NORMAL = 20, '.Heap'
    HEAP_DALVIK_LARGE = 21, '.LOS'
    HEAP_DALVIK_ZYGOTE = 22, '.Zygote'
    HEAP_DALVIK_NON_MOVING = 23, '.NonMoving'

    HEAP_DALVIK_OTHER_LINEARALLOC = 24, '.LinearAlloc'
    HEAP_DALVIK_OTHER_ACCOUNTING = 25, '.GC'
    HEAP_DALVIK_OTHER_ZYGOTE_CODE_CACHE = 26, '.ZygoteJIT'
    HEAP_DALVIK_OTHER_APP_CODE_CACHE = 27, '.AppJIT'
    HEAP_DALVIK_OTHER_COMPILER_METADATA = 28, '.CompilerMetadata'
    HEAP_DALVIK_OTHER_INDIRECT_REFERENCE_TABLE = 29, '.IndirectRef'

    HEAP_DEX_BOOT_VDEX = 30, '.Boot vdex'
    HEAP_DEX_APP_DEX = 31, '.App dex'
    HEAP_DEX_APP_VDEX = 32, '.App vdex'

    HEAP_ART_APP = 33, '.App art'
    HEAP_ART_BOOT = 34, '.Boot art'

    def __init__(self, index, description):
        self._index = index
        self._description = description

    @property
    def description(self):
        return self._description

    @property
    def index(self):
        return self._index


def parse_head(name):
    which_heap = Heap.HEAP_UNKNOWN
    sub_heap = Heap.HEAP_UNKNOWN
    is_swappable = False

    if name.endswith(" (deleted)"):
        name = name[:-len(" (deleted)")]

    if name.startswith("[heap]"):
        which_heap = Heap.HEAP_NATIVE
    elif name.startswith("[anon:libc_malloc]"):
        which_heap = Heap.HEAP_NATIVE
    elif name.startswith("[anon:scudo:"):
        which_heap = Heap.HEAP_NATIVE
    elif name.startswith("[anon:GWP-ASan"):
        which_heap = Heap.HEAP_NATIVE
    elif name.startswith("[stack"):
        which_heap = Heap.HEAP_STACK
    elif name.startswith("[anon:stack_and_tls:"):
        which_heap = Heap.HEAP_STACK
    elif name.endswith(".so"):
        which_heap = Heap.HEAP_SO
        is_swappable = True
    elif name.endswith(".jar"):
        which_heap = Heap.HEAP_JAR
        is_swappable = True
    elif name.endswith(".apk"):
        which_heap = Heap.HEAP_APK
        is_swappable = True
    elif name.endswith(".ttf"):
        which_heap = Heap.HEAP_TTF
        is_swappable = True
    elif name.endswith(".odex") or (len(name) > 4 and name.endswith(".dex")):
        which_heap = Heap.HEAP_DEX
        sub_heap = Heap.HEAP_DEX_APP_DEX
        is_swappable = True
    elif name.endswith(".vdex"):
        which_heap = Heap.HEAP_DEX
        if "@boot" in name or "/boot" in name or "/apex" in name:
            sub_heap = Heap.HEAP_DEX_BOOT_VDEX
        else:
            sub_heap = Heap.HEAP_DEX_APP_VDEX
        is_swappable = True
    elif name.endswith(".oat"):
        which_heap = Heap.HEAP_OAT
        is_swappable = True
    elif name.endswith(".art") or name.endswith(".art]"):
        which_heap = Heap.HEAP_ART
        if "@boot" in name or "/boot" in name or "/apex" in name:
            sub_heap = Heap.HEAP_ART_BOOT
        else:
            sub_heap = Heap.HEAP_ART_APP
        is_swappable = True
    elif name.startswith("/kgsl-3d0"):
        which_heap = Heap.HEAP_GL_DEV
    elif name.startswith("/dev/"):
        which_heap = Heap.HEAP_UNKNOWN_DEV
        if name.startswith("/dev/kgsl-3d0"):
            which_heap = Heap.HEAP_GL_DEV
        elif name.startswith("/dev/ashmem/CursorWindow"):
            which_heap = Heap.HEAP_CURSOR
        elif name.startswith("/dev/ashmem/jit-zygote-cache"):
            which_heap = Heap.HEAP_DALVIK_OTHER
            sub_heap = Heap.HEAP_DALVIK_OTHER_ZYGOTE_CODE_CACHE
        elif name.startswith("/dev/ashmem"):
            which_heap = Heap.HEAP_ASHMEM
    elif name.startswith("/memfd:jit-cache"):
        which_heap = Heap.HEAP_DALVIK_OTHER
        sub_heap = Heap.HEAP_DALVIK_OTHER_APP_CODE_CACHE
    elif name.startswith("/memfd:jit-zygote-cache"):
        which_heap = Heap.HEAP_DALVIK_OTHER
        sub_heap = Heap.HEAP_DALVIK_OTHER_ZYGOTE_CODE_CACHE
    elif name.startswith("[anon:"):
        which_heap = Heap.HEAP_UNKNOWN
        if name.startswith("[anon:dalvik-"):
            which_heap = Heap.HEAP_DALVIK_OTHER
            if name.startswith("[anon:dalvik-LinearAlloc"):
                sub_heap = Heap.HEAP_DALVIK_OTHER_LINEARALLOC
            elif name.startswith("[anon:dalvik-alloc space") or name.startswith("[anon:dalvik-main space"):
                # This is the regular Dalvik heap.
                which_heap = Heap.HEAP_DALVIK
                sub_heap = Heap.HEAP_DALVIK_NORMAL
            elif name.startswith("[anon:dalvik-large object space") or name.startswith(
                    "[anon:dalvik-free list large object space"):
                which_heap = Heap.HEAP_DALVIK
                sub_heap = Heap.HEAP_DALVIK_LARGE
            elif name.startswith("[anon:dalvik-non moving space"):
                which_heap = Heap.HEAP_DALVIK
                sub_heap = Heap.HEAP_DALVIK_NON_MOVING
            elif name.startswith("[anon:dalvik-zygote space"):
                which_heap = Heap.HEAP_DALVIK
                sub_heap = Heap.HEAP_DALVIK_ZYGOTE
            elif name.startswith("[anon:dalvik-indirect ref"):
                sub_heap = Heap.HEAP_DALVIK_OTHER_INDIRECT_REFERENCE_TABLE
            elif name.startswith("[anon:dalvik-jit-code-cache") or name.startswith("[anon:dalvik-data-code-cache"):
                sub_heap = Heap.HEAP_DALVIK_OTHER_APP_CODE_CACHE
            elif name.startswith("[anon:dalvik-CompilerMetadata"):
                sub_heap = Heap.HEAP_DALVIK_OTHER_COMPILER_METADATA
            else:
                sub_heap = Heap.HEAP_DALVIK_OTHER_ACCOUNTING
    elif len(name) > 0:
        which_heap = Heap.HEAP_UNKNOWN_MAP

    return which_heap, sub_heap, is_swappable


class VmaEntry:

    def __init__(self, name, which_heap, sub_heap):
        self.name = name
        self.which_heap = which_heap
        self.sub_heap = sub_heap
        self.pss = 0
        self.swap_pss = 0
        self.rss = 0
        self.swap = 0

    def append_pss(self, pss):
        self.pss += pss

    def append_swap_pss(self, swap_pss):
        self.swap_pss += swap_pss

    def append_rss(self, rss):
        self.rss += rss

    def append_swap(self, swap):
        self.swap += swap


def match_pss(line):
    tmp = re.match(r'Pss:\s+([0-9]*) kB', line, re.I)
    if tmp:
        return tmp


def match_swap_pss(line):
    tmp = re.match(r'SwapPss:\s+([0-9]*) kB', line, re.I)
    if tmp:
        return tmp


def match_rss(line):
    tmp = re.match(r'Rss:\s+([0-9]*) kB', line, re.I)
    if tmp:
        return tmp


def match_swap(line):
    tmp = re.match(r'Swap:\s+([0-9]*) kB', line, re.I)
    if tmp:
        return tmp


def match_head(line):
    return re.match(r'(\w*)-(\w*) (\S*) (\w*) (\w*):(\w*) (\w*) \s*(.*)$', line, re.I)


def parse_smaps(parse_smaps_file):
    which_heap = Heap.HEAP_UNKNOWN
    lines = parse_smaps_file.readlines()

    vma_name = ""
    which_heap = Heap.HEAP_UNKNOWN
    sub_heap = Heap.HEAP_UNKNOWN
    is_swappable = False
    vma_end = 0

    vma_by_name = {}
    vma_entry = None

    for line in lines:
        head = match_head(line)
        if head:
            if len(head.group(8)) == 0 and head.group(1) == vma_end and which_heap == Heap.HEAP_SO:
                # bss section of a shared library
                vma_name = vma_name
            else:
                vma_name = head.group(8)
            which_heap, sub_heap, is_swappable = parse_head(vma_name)
            vma_end = head.group(2)

            vma_entry = vma_by_name.get(vma_name)
            if vma_entry is None:
                vma_entry = VmaEntry(vma_name, which_heap, sub_heap)
                vma_by_name[vma_name] = vma_entry

        pss = match_pss(line)
        if pss:
            vma_entry.append_pss(int(pss.group(1)))

        swap_pss = match_swap_pss(line)
        if swap_pss:
            vma_entry.append_swap_pss(int(swap_pss.group(1)))

        rss = match_rss(line)
        if rss:
            vma_entry.append_rss(int(rss.group(1)))

        swap = match_swap(line)
        if swap:
            vma_entry.append_swap(int(swap.group(1)))

    vma_by_which = {}
    for vma_entry in vma_by_name.values():
        vma_list = vma_by_which.get(vma_entry.which_heap)
        if vma_list is None:
            vma_list = []
            vma_by_which[vma_entry.which_heap] = vma_list
        vma_list.append(vma_entry)

    total_rss = 0
    total_swap = 0
    total_pss = 0
    total_swap_pss = 0
    for which_heap, vma_list in vma_by_which.items():
        pss = 0
        swap_pss = 0
        rss = 0
        swap = 0
        vma_list.sort(key=lambda x: x.pss + x.swap_pss, reverse=True)
        for vma_entry in vma_list:
            pss += vma_entry.pss
            swap_pss += vma_entry.swap_pss
            rss += vma_entry.rss
            swap += vma_entry.swap
            total_pss += vma_entry.pss
            total_swap_pss += vma_entry.swap_pss
            total_rss += vma_entry.rss
            total_swap += vma_entry.swap

        print(f'{which_heap.description}: Pss {pss + swap_pss} kB ({pss} + {swap_pss}), Rss {rss + swap} kB ({rss} + {swap})')
        for vma_entry in vma_list:
            if vma_entry.pss + vma_entry.swap_pss > 0:
                print(f'    {vma_entry.name}: Pss {vma_entry.pss + vma_entry.swap_pss} kB ({vma_entry.pss} + {vma_entry.swap_pss}), Rss {vma_entry.rss + vma_entry.swap} kB ({vma_entry.rss} + {vma_entry.swap})')

    print(f'\nTotal Pss: {total_pss + total_swap_pss} kB (Pss {total_pss} kB + SwapPss {total_swap_pss} kB)')
    print(f'Total Rss: {total_rss + total_swap} kB (Rss {total_rss} kB + Swap {total_swap} kB)')


def pull_smaps(pid):
    if os.system(f'adb shell ls /proc/{pid}/smaps > /dev/null 2>&1') != 0:
        return
    lines = os.popen(f'adb shell cat /proc/{pid}/smaps').readlines()
    f = NamedTemporaryFile('w+t')
    for line in lines:
        f.write(line)
    f.seek(0)
    return f


if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-p", "--pid", type="int", help="pid")
    parser.add_option("-f", "--file", help="smaps file")
    (options, args) = parser.parse_args()

    smaps_file = None
    if options.pid is not None:
        smaps_file = pull_smaps(options.pid)
        if smaps_file is None:
            print(f'/proc/{options.pid}/smaps cannot be accessed')
        else:
            parse_smaps(smaps_file)
    elif options.file is not None:
        smaps_file = open(options.file, 'r')
        parse_smaps(smaps_file)
    else:
        print("No pid or file specified\n")
        parser.print_help()


