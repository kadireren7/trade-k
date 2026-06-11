"""Claude yanıtı ayrıştırma testleri."""
import ai


def test_parse_multiple_suggestions():
    text = ('Özet cümlesi.\n'
            'ONERILER: [{"islem":"AL","sembol":"GC=F","tutar_usdt":600,'
            '"basari_yuzdesi":62,"gerekce":"altın destekte"},'
            '{"islem":"SAT","sembol":"BTCUSDT","tutar_usdt":500,'
            '"basari_yuzdesi":55,"gerekce":"momentum zayıf"}]')
    suggs = ai.parse_suggestions(text)
    assert len(suggs) == 2
    assert suggs[0].islem == "AL" and suggs[0].sembol == "GC=F"
    assert suggs[0].basari_yuzdesi == 62
    assert suggs[1].islem == "SAT" and suggs[1].tutar_usdt == 500


def test_parse_single_oneri_format():
    text = 'Analiz...\nONERI: {"islem":"AL","sembol":"ETHUSDT","tutar_usdt":300,"basari_yuzdesi":58,"gerekce":"x"}'
    suggs = ai.parse_suggestions(text)
    assert len(suggs) == 1
    assert suggs[0].sembol == "ETHUSDT"


def test_parse_filters_bekle():
    text = ('ONERILER: [{"islem":"BEKLE","sembol":"BTCUSDT","tutar_usdt":0,'
            '"basari_yuzdesi":0,"gerekce":"net değil"},'
            '{"islem":"AL","sembol":"GC=F","tutar_usdt":400,'
            '"basari_yuzdesi":50,"gerekce":"y"}]')
    suggs = ai.parse_suggestions(text)
    assert len(suggs) == 1
    assert suggs[0].islem == "AL"


def test_parse_garbage_returns_empty():
    assert ai.parse_suggestions("hiç json yok burada") == []
    assert ai.parse_suggestions("ONERILER: [bozuk json") == []
    assert ai.parse_suggestions('ONERI: {"islem":"AL"  bozuk') == []


def test_strip_machine_lines():
    text = 'Özet metni.\nONERILER: [{"islem":"AL","sembol":"X","tutar_usdt":1,"basari_yuzdesi":50,"gerekce":"g"}]'
    assert ai.strip_machine_lines(text) == "Özet metni."
    text2 = 'Analiz.\nONERI: {"islem":"BEKLE","sembol":"X","tutar_usdt":0,"basari_yuzdesi":0,"gerekce":"g"}'
    assert ai.strip_machine_lines(text2) == "Analiz."
