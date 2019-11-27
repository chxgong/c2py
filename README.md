# c2py

This tool is used for generate Source Files for C/C++ Extensions(.pyd files) from C/C++ headers.

## Different with using libraries:

If you want to use C/C++ code in python. You can:
 * ```ctypes```
 * Writing C Extension with ```boost.python``` or ```pybind11``` or some other libraries.

In both ways, you must write your own code to generate a C Extension(.pyd file).
Writing your own code require that you are experienced in C/C++ 
and **TAKES A LONG TIME** to coding.

## Different with swig(tool)

You can also consider swig.

Swig is a well developed tool, which means that it has fewer bugs.
But since swig uses a simplified parser, you have to maintain an extra interface file.
And as its name, it is just a simple wrapper. You can always build a extension from swig, 
but that extension may be hard to use, unstable or even unusable. 

c2py use clang as its parser, you don't have to maintain any extra file.
And it has some built-in (and optional) transforms that will try to solve some 
special C/C++ code to make final python extension usable and stable.

------

In a word, with c2py you don't need to be so experienced in C/C++.
It will try its best to help you 
resolve all the problem you might face 
when generating a binding from C/C++ to python.

All you need(in ideal situation), is just run c2py and then, build.

## Project goal
We hope people can use any C/C++ code by just run c2py & build,
leaving all the trouble to c2py.

## Features:
 * to produce a pyd file(or its source) instead of just providing a binding library.
 * handles almost all the trouble you may face when writing your own code.
 * fully typed type hint files(.pyi files).
 * generated pyd has a identical layout as C++ namespace.
 * recognize almost everything in C++.(See [TODO.txt](./TODO.txt) for a full list.)
 * recognize constant declared by #define. (people writing C likes this)
 * Functions, class method, getters & setters can be customized using C++ template specialization
  if c2py is not good enough.(Wish you contribute your code to c2py instead of writing your own private solution)

## Requirements

to run c2py, you need Python3.6 or newer version.
to build generated c++ sources, you need a compiler that supports C++17. they are:
 
 * Visual Studio 2017 or newer version. Visual Studio 2019 is recommanded.
 * gcc7 or newer version. Anything works.

## install
```bash
pip install https://github.com/nanoric/c2py/archive/master.zip
```

## Usage
```text
> c2py generate --help
Usage: c2py generate [OPTIONS] MODULE_NAME [FILES]...

  Converts C/C++ .h files into python module source files. All matching is
  based on c++ qualified name, using regex.

Options:
  -e, --encoding TEXT             encoding of input files, default is
                                  utf-8(use python's encoding library)
  -I, --include-path TEXT         additional include paths
  -D TEXT                         additional pre-defined definitions
  -A, --additional-include TEXT   additional include files. These files will
                                  be included in output cxx file, but skipped
                                  by parser.
  -ew, --string-encoding-windows TEXT
                                  encoding used to get & set string. This
                                  value is used to construct std::locale. use
                                  `locale -a` to show all the locates
                                  supported. default is utf-8, which is the
                                  internal encoding used by pybind11.
  -el, --string-encoding-linux TEXT
                                  encoding used to get & set string. This
                                  value is used to construct std::locale. use
                                  `locale -a` to show all the locates
                                  supported. default is utf-8, which is the
                                  internal encoding used by pybind11.
  -i, --ignore-pattern TEXT       ignore symbols matched
  --no-callback-pattern TEXT      disable generation of callback for functions
                                  matched (for some virtual method used as
                                  undocumented API)
  --no-transform-pattern TEXT     disable applying transforms(changing its
                                  signature) into functions matched (for some
                                  virtual method used as callback only)
  --inout-arg-pattern TEXT        make symbol(arguments only) as input_output
  --output-arg-pattern TEXT       make symbol(arguments only) as output only
  --no-caster-pattern TEXT        don't generate caster for symbol
  --m2c / --no-m2c                treat const macros as global variable
  --ignore-underline-prefixed / --no-ignore-underline-prefixed
                                  ignore global variables starts with
                                  underline
  --ignore-unsupported / --no-ignore-unsupported
                                  ignore functions that has unsupported
                                  argument
  --inject-symbol-name / --no-inject-symbol-name
                                  Add comment to describe every generated
                                  symbol's name
  -o, --output-dir PATH           module source output directory
  -p, --pyi-output-dir PATH       pyi files output directory
  --clear-output-dir / --no-clear-output-dir
  --clear-pyi-output-dir / --no-clear-pyi-output-dir
  --copy-c2py-includes TEXT       copy all c2py include files, excluding input
                                  files to specific dir.
  -m, --max-lines-per-file INTEGER RANGE
  --generate-setup TEXT           if set, generate setup.py into this location
  --setup-lib-dir TEXT
  --setup-lib TEXT
  --setup-use-patches / --setup-no-use-patches
  --enforce-version TEXT          Check if c2py version matches. If not match,
                                  print error and exit. Use this to prevent
                                  generating code from incompatible version of
                                  c2py.
  --help                          Show this message and exit.


```

## Example
Just generate & run generated ```setup.py```: 
```bash
c2py generate vnctp                                     \
    ThostFtdcMdApi.h                                    \
    ThostFtdcTraderApi.h                                \
    ThostFtdcUserApiDataType.h                          \
    ThostFtdcUserApiStruct.h                            \
    -I                          vnctp/include/          \
    --no-callback-pattern       ".*Api::.*"             \
    --string-encoding-windows   .936                    \
    --string-encoding-linux     zh_CN.GB18030           \
                                                        \
    --copy-c2py-includes   vnctp/include/               \
    --output-dir                vnctp/generated_files/  \
    --clear-output-dir                                  \
                                                        \
    --generate-setup            .                       \
    --setup-lib-dir             vnctp/libs/             \
    --setup-lib                 thostmduserapi          \
    --setup-lib                 thosttraderapi

python ./setup.py build
```
