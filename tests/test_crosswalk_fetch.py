from vn_admin_units import crosswalk_fetch as cf


def test_tier_config_province_and_district():
    assert cf.TIER_CAP["province"] == "1"
    assert cf.TIER_CAP["district"] == "2"


def test_cache_relpath_by_tier():
    assert cf.cache_relpath("province", "01/01/2004", "01/01/2005") \
        == "crosswalk/province_2004-01-01_2005-01-01.xls"
    assert cf.cache_relpath("district", "01/01/2013", "01/01/2014") \
        == "crosswalk/district_2013-01-01_2014-01-01.xls"


def test_yearly_windows():
    assert cf.yearly_windows(2004, 2005) == [("01/01/2004", "01/01/2005"),
                                             ("01/01/2005", "01/01/2006")]
