
    // ============= GENERIC PARSERS (23 VERIFIED EXCHANGES) =============
    bool parse_generic_array(const std::string& json, OrderBook& book) {
        size_t s, e;
        if (find_array(json, "bids", s, e)) parse_arr_levels(json.substr(s, e-s), book.bids);
        if (find_array(json, "asks", s, e)) parse_arr_levels(json.substr(s, e-s), book.asks);
        return book.is_valid();
    }
    void parse_arr_levels(const std::string& arr, std::vector<PriceLevel>& levels) {
        size_t p = 0;
        while (p < arr.size()) {
            size_t b = arr.find('[', p);
            if (b == std::string::npos) break;
            size_t c = arr.find(']', b);
            if (c == std::string::npos) break;
            std::string ent = arr.substr(b+1, c-b-1);
            double pr = 0, am = 0; size_t v = 0;
            while (v < ent.size() && (ent[v] == ' ' || ent[v] == '"')) v++;
            size_t ve = v;
            while (ve < ent.size() && ent[ve] != ',' && ent[ve] != '"') ve++;
            if (ve > v) pr = std::strtod(ent.substr(v, ve-v).c_str(), nullptr);
            v = ent.find(',', ve); if (v == std::string::npos) { p = c+1; continue; } v++;
            while (v < ent.size() && (ent[v] == ' ' || ent[v] == '"')) v++;
            ve = v; while (ve < ent.size() && ent[ve] != ',' && ent[ve] != '"') ve++;
            if (ve > v) am = std::strtod(ent.substr(v, ve-v).c_str(), nullptr);
            if (pr > 1000 && am > 0) levels.push_back(PriceLevel{pr, am});
            p = c+1;
        }
    }
    bool parse_generic_data(const std::string& json, OrderBook& book) {
        size_t d = json.find("\"data\"");
        return d != std::string::npos ? parse_generic_array(json.substr(d), book) : parse_generic_array(json, book);
    }
    bool parse_kraken(const std::string& json, OrderBook& book) {
        size_t r = json.find("\"result\"");
        return r != std::string::npos ? parse_generic_array(json.substr(r), book) : false;
    }
    bool parse_okx(const std::string& json, OrderBook& book) {
        size_t d = json.find("\"data\"");
        return d != std::string::npos ? parse_generic_array(json.substr(d), book) : false;
    }
    bool parse_htx(const std::string& json, OrderBook& book) {
        size_t t = json.find("\"tick\"");
        return t != std::string::npos ? parse_generic_array(json.substr(t), book) : false;
    }
    bool parse_bitfinex(const std::string& json, OrderBook& book) {
        size_t pos = 0;
        while (pos < json.size()) {
            size_t b = json.find('[', pos);
            if (b == std::string::npos) break;
            size_t c = json.find(']', b);
            if (c == std::string::npos) break;
            std::string ent = json.substr(b+1, c-b-1);
            if (ent.find('[') != std::string::npos) { pos = b+1; continue; }
            double pr=0, cnt=0, am=0;
            if (sscanf(ent.c_str(), "%lf,%lf,%lf", &pr, &cnt, &am) == 3 && pr > 1000) {
                if (am > 0) book.bids.push_back(PriceLevel{pr, am});
                else book.asks.push_back(PriceLevel{pr, -am});
            }
            pos = c+1;
        }
        return book.is_valid();
    }
    bool parse_coinex(const std::string& json, OrderBook& book) {
        size_t d = json.find("\"depth\"");
        return d != std::string::npos ? parse_generic_array(json.substr(d), book) : parse_generic_data(json, book);
    }
    bool parse_cryptocom(const std::string& json, OrderBook& book) {
        size_t r = json.find("\"result\"");
        return r != std::string::npos ? parse_generic_data(json.substr(r), book) : false;
    }
    bool parse_ascendex(const std::string& json, OrderBook& book) {
        size_t d1 = json.find("\"data\"");
        if (d1 == std::string::npos) return false;
        size_t d2 = json.find("\"data\"", d1 + 6);
        return d2 != std::string::npos ? parse_generic_array(json.substr(d2), book) : parse_generic_data(json, book);
    }

