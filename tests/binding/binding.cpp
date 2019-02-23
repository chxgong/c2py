// binding.cpp : This file contains the 'main' function. Program execution begins and ends there.
//

#include "pch.h"
#include <iostream>

#include <autocxxpy/autocxxpy.hpp>
#include <boost/callable_traits.hpp>
#include <brigand/brigand.hpp>

#include <autocxxpy/wrappers/cfunction.h>

using namespace autocxxpy;

using callback_t = int(*)(int, void *);

int func(int v, callback_t callback, void * user)
{
    return callback(v, user);
}

int func2(int v, int, int, int, callback_t callback, void * user, int, int)
{
    return callback(v, user);
}


int nofail1(void)
{
    return 1;
}

int nofail2(int v, callback_t callback, int)
{
    return 1;
}


int nofail3(int v, callback_t callback)
{
    return 1;
}


PYBIND11_MODULE(binding, m)
{
    m.def("func",
        autocxxpy::calling_wrapper_v<&func>
        //autocxxpy::c_function_pointer_to_std_function<std::integral_constant<decltype(&func), &func>>::value
        //autocxxpy::wrap_c_function_ptr<&func>()
    );
    m.def("func2",
        autocxxpy::calling_wrapper_v<&func2>
    );

    autocxxpy::calling_wrapper_v<&nofail1>;
    autocxxpy::calling_wrapper_v<&nofail2>;
    autocxxpy::calling_wrapper_v<&nofail3>;
}