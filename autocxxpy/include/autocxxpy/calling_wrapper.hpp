#pragma once

#include "utils/functional.hpp"
#include "dispatcher.hpp"
#include "brigand.hpp"

#include "wrappers/cfunction.h"
#include "wrappers/no_gil.hpp"
#include "wrappers/string_array.h"

namespace autocxxpy
{

    /*
    example to change the calling method:

    @startcode pp
    template <>
    struct calling_wrapper<&A::func2>
    {
        static constexpr auto value = [](){return 1;};
    };
    @endcode
    */

    // this is an example of transform
    template <class T>
    struct default_transform
    {
        using type = default_transform; //  used by brigand::apply. should refer to this class itself.
        using value_type = decltype(T::value);
        static constexpr value_type value = wrap_c_function_ptr<T>(); // store the result here
    };

    template <template <class> class T>
    struct transform_holder
    {
        template <class method_constant>
        using transform = T<method_constant>;
    };

	template <template <class method_constant, class integral_constant> class original_transform, size_t index>
	struct indexed_transform_holder
	{
        template <class method_constant>
        using transform = original_transform<method_constant, std::integral_constant<int, index>>;
	};

    using trans_list = brigand::list <
        transform_holder<c_function_pointer_to_std_function_transform>,
        transform_holder<string_array_transform>
        //, transform_holder<no_gil_transform>  // no gil transform should be the last one
    >;

    template <class T, class TransformHolder>
    struct apply_transform_element : TransformHolder::template transform<T>{};

    template <auto method>
    constexpr auto apply_transform_impl()
    {
        using namespace brigand;

        using result = fold<trans_list,
            std::integral_constant<decltype(method), method>,
            apply_transform_element<_state, _element>
        >;
        return result::value;
	}

	template <class MethodConstant, class TransformList>
	struct apply_function_transform
	{
	public:
		using type=apply_function_transform;
        using result = brigand::fold<TransformList,
            MethodConstant,
            apply_transform_element<brigand::_state, brigand::_element>
        >;
		using value_type = decltype(result::value);
		static constexpr value_type value = result::value;
	};

    template <auto method>
    struct default_calling_wrapper
    {
    public:
        using ty = decltype(apply_transform_impl<method>());
        static constexpr ty value = apply_transform_impl<method>();
    };

    template <auto method>
    struct calling_wrapper : default_calling_wrapper<method>
    {};

    template <auto method>
    auto calling_wrapper_v = calling_wrapper<method>::value;
}
