#include <iostream>

#include <autocxxpy/autocxxpy.hpp>
#include <autocxxpy/base/type.h>
#include <autocxxpy/wrappers/new/output_argument.hpp>

#include <pybind11/pybind11.h>

using namespace autocxxpy;

static void f(int* a)
{
	*a = 1;
}

static int f2(int* a, int *b)
{
	*a = 11;
	*b = 12;
	return 1;
}

static int f3(int* a, int *b, int *c)
{
	*a = 21;
	*b = 22;
	*c = 23;
	return 1;
}

PYBIND11_MODULE(wrap_argument_as_output, m)
{

	using namespace brigand;
	namespace ct = boost::callable_traits;
	constexpr auto method = &f;
	using namespace brigand;
	namespace ct = boost::callable_traits;
	using ret_t = typename ct::return_type<decltype(method)>::type;
	static_assert(std::is_void_v<ret_t>);


	using Method = function_constant<&f>;
	using Method2 = function_constant<&f2>;
	using Method3 = function_constant<&f3>;
	m.def("f", output_argument_transform<Method, std::integral_constant<int, 0>>::value);
	m.def("f2",
		apply_function_transform<
		function_constant<&f2>,
		brigand::list<
		indexed_transform_holder<output_argument_transform, 0>,
		indexed_transform_holder<output_argument_transform, 0>
		>
		>::value
	);

	m.def("f3",
		apply_function_transform<function_constant<&f3>,
		brigand::list<
		indexed_transform_holder<output_argument_transform, 0>,
		indexed_transform_holder<output_argument_transform, 0>,
		indexed_transform_holder<output_argument_transform, 0>
		>
		>::value
	);
}